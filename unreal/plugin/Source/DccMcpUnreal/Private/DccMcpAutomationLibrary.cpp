#include "DccMcpAutomationLibrary.h"

#include "Runtime/Launch/Resources/Version.h"
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
#include "AI/Navigation/NavigationSystem.h"
#else
#include "Blueprint/AIBlueprintHelperLibrary.h"
#endif
#include "Containers/Ticker.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "AssetRegistry/AssetRegistryModule.h"
#else
#include "AssetRegistryModule.h"
#endif
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Framework/Application/SlateApplication.h"
#include "Framework/Docking/TabManager.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerInput.h"
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
#include "GenericPlatform/GenericPlatformInputDeviceMapper.h"
#endif
#include "InputCoreTypes.h"
#include "HAL/FileManager.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "GeometryCollection/GeometryCollectionActor.h"
#include "GeometryCollection/GeometryCollectionAlgo.h"
#include "GeometryCollection/GeometryCollectionClusteringUtility.h"
#include "GeometryCollection/GeometryCollectionComponent.h"
#include "GeometryCollection/GeometryCollectionEngineConversion.h"
#include "GeometryCollection/GeometryCollectionObject.h"
#endif
#include "Interfaces/IPluginManager.h"
#include "LevelEditor.h"
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
#include "ILevelViewport.h"
#elif ENGINE_MAJOR_VERSION == 4
#include "IAssetViewport.h"
#else
#include "SLevelViewport.h"
#endif
#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Math/UnrealMathUtility.h"
#include "Misc/AutomationTest.h"
#include "Misc/Guid.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "ScopedTransaction.h"
#include "Templates/SharedPointer.h"
#include "UObject/Package.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "UObject/SavePackage.h"
#endif
#include "UObject/UObjectGlobals.h"
#include "UObject/UObjectIterator.h"
#include "Engine/Texture.h"
#include "Widgets/SWindow.h"
#include "Widgets/Docking/SDockTab.h"
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 8)
#include "NiagaraEmitter.h"
#include "NiagaraExternalSystemEditorUtilities.h"
#include "NiagaraRendererProperties.h"
#include "NiagaraScript.h"
#include "NiagaraSystem.h"
#include "NiagaraTypes.h"
#include "ObjectTools.h"
#endif

namespace
{
constexpr TCHAR FabModuleName[] = TEXT("Fab");
constexpr TCHAR FabApiClassPath[] = TEXT("/Script/Fab.FabBrowserApi");
constexpr TCHAR FabListingPrefix[] = TEXT("https://fab.com/plugins/ue5/listings/");

#if ENGINE_MAJOR_VERSION >= 5
using FDccMcpCoreTicker = FTSTicker;
using FDccMcpTickerHandle = FTSTicker::FDelegateHandle;
#else
using FDccMcpCoreTicker = FTicker;
using FDccMcpTickerHandle = FDelegateHandle;
#endif
FDccMcpTickerHandle PieInputSteeringTickerHandle;
TWeakObjectPtr<UWorld> PieSteeringWorld;
TWeakObjectPtr<APlayerController> PieSteeringController;
TWeakObjectPtr<APawn> PieSteeringPawn;

struct FDccMcpOwnedKey
{
    TWeakObjectPtr<UWorld> World;
    TWeakObjectPtr<APlayerController> Controller;
    TWeakObjectPtr<UPlayerInput> Receiver;
    TWeakObjectPtr<APawn> Pawn;
    FKey Key;
    bool bPressAttempted = false;
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    FInputDeviceId Device;
#endif
};
TMap<FString, FDccMcpOwnedKey> OwnedPieKeys;

bool DeliverOwnedKey(const FDccMcpOwnedKey& State, bool bPressed)
{
    UWorld* World = State.World.Get();
    APlayerController* Controller = State.Controller.Get();
    UPlayerInput* Receiver = State.Receiver.Get();
    if (!World || !Controller || !Receiver || Controller->GetWorld() != World
        || Receiver->GetOuter() != Controller)
    {
        return false;
    }
    // InputKey's bool indicates action consumption, not key-state acceptance.
    // Deliver directly to the captured receiver, even if PlayerInput was replaced.
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    Receiver->InputKey(FInputKeyParams(State.Key, bPressed ? IE_Pressed : IE_Released,
        bPressed ? 1.0 : 0.0, false, State.Device));
#else
    Receiver->InputKey(State.Key, bPressed ? IE_Pressed : IE_Released, bPressed ? 1.0f : 0.0f, false);
#endif
    return true;
}

struct FDccMcpInputSteeringState
{
    explicit FDccMcpInputSteeringState(TArray<FVector>&& InWaypoints)
        : Waypoints(MoveTemp(InWaypoints))
    {
    }

    TArray<FVector> Waypoints;
    int32 WaypointIndex = 1;
};

void StopPieInputSteeringTicker()
{
    if (PieInputSteeringTickerHandle.IsValid())
    {
        FDccMcpCoreTicker::GetCoreTicker().RemoveTicker(PieInputSteeringTickerHandle);
        PieInputSteeringTickerHandle.Reset();
    }
}

UClass* ResolveFabApiClass()
{
    const TSharedPtr<IPlugin> FabPlugin = IPluginManager::Get().FindPlugin(FabModuleName);
    if (!FabPlugin.IsValid() || !FabPlugin->IsEnabled())
    {
        return nullptr;
    }

    if (!FModuleManager::Get().IsModuleLoaded(FabModuleName))
    {
        FModuleManager::Get().LoadModulePtr<IModuleInterface>(FabModuleName);
    }
    return FindObject<UClass>(nullptr, FabApiClassPath);
}

UObject* NewFabApi()
{
    UClass* FabApiClass = ResolveFabApiClass();
    return FabApiClass ? NewObject<UObject>(GetTransientPackage(), FabApiClass) : nullptr;
}

bool InvokeFabNoArgs(UObject* FabApi, const FName FunctionName)
{
    if (!FabApi || !IsInGameThread())
    {
        return false;
    }
    UFunction* Function = FabApi->FindFunction(FunctionName);
    if (!Function)
    {
        return false;
    }
    FabApi->ProcessEvent(Function, nullptr);
    return true;
}

bool InvokeFabString(UObject* FabApi, const FName FunctionName, const FString& Value)
{
    if (!FabApi || !IsInGameThread())
    {
        return false;
    }
    UFunction* Function = FabApi->FindFunction(FunctionName);
    if (!Function)
    {
        return false;
    }

    struct FParams
    {
        FString Value;
    } Params{Value};
    FabApi->ProcessEvent(Function, &Params);
    return true;
}

bool InvokeFabStringResult(UObject* FabApi, const FName FunctionName, FString& OutValue)
{
    if (!FabApi || !IsInGameThread())
    {
        return false;
    }
    UFunction* Function = FabApi->FindFunction(FunctionName);
    if (!Function)
    {
        return false;
    }

    struct FParams
    {
        FString ReturnValue;
    } Params;
    FabApi->ProcessEvent(Function, &Params);
    OutValue = MoveTemp(Params.ReturnValue);
    return true;
}

FString SerializeJson(const TSharedRef<FJsonObject>& Root)
{
    FString Output;
    const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Output);
    FJsonSerializer::Serialize(Root, Writer);
    return Output;
}

FString MaterialGraphError(const FString& ErrorCode, const FString& Message, bool bRollbackCompleted = true)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), false);
    Root->SetStringField(TEXT("error_code"), ErrorCode);
    Root->SetStringField(TEXT("message"), Message);
    Root->SetBoolField(TEXT("rollback_completed"), bRollbackCompleted);
    return SerializeJson(Root);
}

TArray<TSharedPtr<FJsonValue>> JsonStringArray(const TArray<FString>& Values)
{
    TArray<TSharedPtr<FJsonValue>> Result;
    Result.Reserve(Values.Num());
    for (const FString& Value : Values)
    {
        Result.Add(MakeShared<FJsonValueString>(Value));
    }
    return Result;
}

FString EditorViewportFocusResult(
    const TArray<FString>& CloseRequestedItems,
    const TArray<FString>& ClosedItems,
    const TArray<FString>& RemainingLogTabs,
    bool bLevelEditorActivated,
    bool bViewportFocused,
    const FString& ErrorCode = FString(),
    const FString& Message = FString()
)
{
    const bool bPostconditionMet = ErrorCode.IsEmpty()
        && RemainingLogTabs.Num() == 0
        && bLevelEditorActivated
        && bViewportFocused;
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), bPostconditionMet);
    Root->SetArrayField(TEXT("close_requested_items"), JsonStringArray(CloseRequestedItems));
    Root->SetArrayField(TEXT("closed_items"), JsonStringArray(ClosedItems));
    Root->SetArrayField(TEXT("remaining_log_tabs"), JsonStringArray(RemainingLogTabs));
    Root->SetBoolField(TEXT("level_editor_activated"), bLevelEditorActivated);
    Root->SetBoolField(TEXT("viewport_focused"), bViewportFocused);
    Root->SetBoolField(TEXT("postcondition_met"), bPostconditionMet);
    if (!bPostconditionMet)
    {
        Root->SetStringField(
            TEXT("error_code"),
            ErrorCode.IsEmpty() ? TEXT("postcondition_not_met") : ErrorCode
        );
        Root->SetStringField(
            TEXT("message"),
            Message.IsEmpty() ? TEXT("Level Editor viewport focus was not verified") : Message
        );
    }
    return SerializeJson(Root);
}

FVector2MaterialInput* GetCustomizedUvInput(UMaterial* Material, int32 CustomizedUvIndex)
{
    if (!Material || CustomizedUvIndex < 0 || CustomizedUvIndex >= 8)
    {
        return nullptr;
    }
#if ENGINE_MAJOR_VERSION >= 5
    UMaterialEditorOnlyData* EditorOnlyData = Material->GetEditorOnlyData();
    return EditorOnlyData ? &EditorOnlyData->CustomizedUVs[CustomizedUvIndex] : nullptr;
#else
    return &Material->CustomizedUVs[CustomizedUvIndex];
#endif
}

bool MaterialOwnsExpression(UMaterial* Material, UMaterialExpression* SourceExpression)
{
    if (!Material || !SourceExpression)
    {
        return false;
    }
#if ENGINE_MAJOR_VERSION >= 5
    UMaterialEditorOnlyData* EditorOnlyData = Material->GetEditorOnlyData();
    return EditorOnlyData
        && EditorOnlyData->ExpressionCollection.Expressions.Contains(SourceExpression);
#else
    return Material->Expressions.Contains(SourceExpression);
#endif
}

FString MaterialOutputName(const FExpressionOutput& Output)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26
    return Output.OutputName;
#else
    return Output.OutputName.ToString();
#endif
}

FString OutputNameAt(UMaterialExpression* SourceExpression, int32 SourceOutputIndex)
{
    if (!SourceExpression)
    {
        return FString();
    }
    const TArray<FExpressionOutput>& Outputs = SourceExpression->GetOutputs();
    return Outputs.IsValidIndex(SourceOutputIndex)
        ? MaterialOutputName(Outputs[SourceOutputIndex])
        : FString();
}

void AddCustomizedUvConnectionFields(
    const TSharedRef<FJsonObject>& Root,
    UMaterial* Material,
    int32 CustomizedUvIndex
)
{
    FVector2MaterialInput* Input = GetCustomizedUvInput(Material, CustomizedUvIndex);
    UMaterialExpression* Expression = Input ? Input->Expression : nullptr;
    Root->SetNumberField(TEXT("customized_uv_index"), CustomizedUvIndex);
    Root->SetBoolField(TEXT("connected"), Expression != nullptr);
    Root->SetStringField(TEXT("source_expression_name"), Expression ? Expression->GetName() : FString());
    Root->SetStringField(
        TEXT("source_expression_guid"),
        Expression ? Expression->MaterialExpressionGuid.ToString(EGuidFormats::DigitsWithHyphens) : FString()
    );
    Root->SetNumberField(TEXT("source_output_index"), Expression ? Input->OutputIndex : -1);
    Root->SetStringField(
        TEXT("source_output_name"),
        Expression ? OutputNameAt(Expression, Input->OutputIndex) : FString()
    );
    Root->SetNumberField(TEXT("num_customized_uvs"), Material ? Material->NumCustomizedUVs : 0);
    UPackage* Package = Material ? Material->GetOutermost() : nullptr;
    Root->SetBoolField(TEXT("package_dirty"), Package ? Package->IsDirty() : false);
}

bool SaveAssetPackage(UObject* Asset, const FString& Filename)
{
    UPackage* Package = Asset ? Asset->GetOutermost() : nullptr;
    if (!Package || Filename.IsEmpty())
    {
        return false;
    }
#if ENGINE_MAJOR_VERSION >= 5
    FSavePackageArgs SaveArgs;
    SaveArgs.TopLevelFlags = RF_Public | RF_Standalone;
    SaveArgs.SaveFlags = SAVE_NoError;
    SaveArgs.bWarnOfLongFilename = false;
    SaveArgs.bSlowTask = false;
    return UPackage::SavePackage(Package, Asset, *Filename, SaveArgs);
#else
    return UPackage::SavePackage(
        Package,
        Asset,
        RF_Public | RF_Standalone,
        *Filename,
        GError,
        nullptr,
        false,
        false,
        SAVE_NoError,
        nullptr,
        FDateTime::MinValue(),
        false
    );
#endif
}

bool SaveMaterialPackage(UMaterial* Material, const FString& Filename)
{
    return SaveAssetPackage(Material, Filename);
}

bool MaterialInstanceParameterMatches(const FScalarParameterValue& Value, FName Name)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    return Value.ParameterName == Name;
#else
    return Value.ParameterInfo == FMaterialParameterInfo(Name);
#endif
}

bool MaterialInstanceParameterMatches(const FVectorParameterValue& Value, FName Name)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    return Value.ParameterName == Name;
#else
    return Value.ParameterInfo == FMaterialParameterInfo(Name);
#endif
}

bool MaterialInstanceParameterMatches(const FTextureParameterValue& Value, FName Name)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    return Value.ParameterName == Name;
#else
    return Value.ParameterInfo == FMaterialParameterInfo(Name);
#endif
}

void SetMaterialInstanceScalarOverride(UMaterialInstanceConstant* Instance, FName Name, float Value)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    Instance->SetScalarParameterValueEditorOnly(Name, Value);
#else
    Instance->SetScalarParameterValueEditorOnly(FMaterialParameterInfo(Name), Value);
#endif
}

void SetMaterialInstanceVectorOverride(UMaterialInstanceConstant* Instance, FName Name, FLinearColor Value)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    Instance->SetVectorParameterValueEditorOnly(Name, Value);
#else
    Instance->SetVectorParameterValueEditorOnly(FMaterialParameterInfo(Name), Value);
#endif
}

void SetMaterialInstanceTextureOverride(UMaterialInstanceConstant* Instance, FName Name, UTexture* Value)
{
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    Instance->SetTextureParameterValueEditorOnly(Name, Value);
#else
    Instance->SetTextureParameterValueEditorOnly(FMaterialParameterInfo(Name), Value);
#endif
}

bool HasPieWorld()
{
    if (GEditor && GEditor->PlayWorld)
    {
        return true;
    }
    if (!GEngine)
    {
        return false;
    }
    for (const FWorldContext& WorldContext : GEngine->GetWorldContexts())
    {
        if (WorldContext.WorldType == EWorldType::PIE && WorldContext.World())
        {
            return true;
        }
    }
    return false;
}

APlayerController* ResolveLocalPlayerController(UWorld* World, UGameInstance* GameInstance)
{
    if (!World)
    {
        return nullptr;
    }
    if (GameInstance)
    {
        if (APlayerController* PlayerController = GameInstance->GetFirstLocalPlayerController(World))
        {
            return PlayerController;
        }
    }
    if (GEngine)
    {
        if (APlayerController* PlayerController = GEngine->GetFirstLocalPlayerController(World))
        {
            return PlayerController;
        }
    }
    return World->GetFirstPlayerController();
}

bool IsPlayableWorld(const UWorld* World)
{
    return World
        && (World->WorldType == EWorldType::PIE
            || World->WorldType == EWorldType::Game
            || World->WorldType == EWorldType::GamePreview);
}

APlayerController* GetPiePlayerController()
{
    UWorld* PlayWorld = GEditor ? GEditor->PlayWorld : nullptr;
    if (PlayWorld)
    {
        if (APlayerController* PlayerController = ResolveLocalPlayerController(PlayWorld, PlayWorld->GetGameInstance()))
        {
            return PlayerController;
        }
    }

    // During PIE travel, PlayWorld can briefly keep the server or previous world while
    // the playable client world is already active. Resolve that world from the engine's
    // authoritative contexts so input survives level transitions.
    if (!GEngine)
    {
        return nullptr;
    }
    for (const FWorldContext& WorldContext : GEngine->GetWorldContexts())
    {
        if (WorldContext.WorldType != EWorldType::PIE
            && WorldContext.WorldType != EWorldType::Game
            && WorldContext.WorldType != EWorldType::GamePreview)
        {
            continue;
        }
        UWorld* PieWorld = WorldContext.World();
        if (!PieWorld || PieWorld == PlayWorld)
        {
            continue;
        }
        if (APlayerController* PlayerController = ResolveLocalPlayerController(
                PieWorld,
                WorldContext.OwningGameInstance
            ))
        {
            return PlayerController;
        }
    }

    // A traveling PIE client can temporarily detach its playable world from the
    // engine context list. The object registry remains authoritative for live
    // controllers, so use it as the final local-player fallback.
    for (TObjectIterator<APlayerController> It; It; ++It)
    {
        APlayerController* PlayerController = *It;
        if (IsValid(PlayerController)
            && !PlayerController->HasAnyFlags(RF_ClassDefaultObject | RF_ArchetypeObject)
            && PlayerController->IsLocalController()
            && IsPlayableWorld(PlayerController->GetWorld()))
        {
            return PlayerController;
        }
    }
    return nullptr;
}

AActor* FindPieActorByName(UWorld* World, const FString& ActorName)
{
    if (!World || ActorName.IsEmpty())
    {
        return nullptr;
    }
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Candidate = *It;
        if (IsValid(Candidate) && Candidate->GetName().Equals(ActorName, ESearchCase::CaseSensitive))
        {
            return Candidate;
        }
    }
    return nullptr;
}

TArray<FVector> FindNavigationWaypoints(APawn* Pawn, const FVector& TargetLocation)
{
    return {Pawn->GetActorLocation(), TargetLocation};
}

bool StartPieInputSteeringInternal(
    UWorld* World,
    APlayerController* PlayerController,
    APawn* Pawn,
    const FVector& TargetLocation,
    AActor* TargetActor
)
{
    if (!IsInGameThread() || !IsValid(World) || !IsPlayableWorld(World)
        || !IsValid(PlayerController) || !PlayerController->IsLocalController()
        || !IsValid(Pawn) || PlayerController->GetPawn() != Pawn || TargetLocation.ContainsNaN())
    {
        return false;
    }
    if (PlayerController->GetWorld() != World || Pawn->GetWorld() != World
        || (TargetActor && TargetActor->GetWorld() != World))
    {
        return false;
    }

    TArray<FVector> Waypoints = FindNavigationWaypoints(Pawn, TargetLocation);
    StopPieInputSteeringTicker();
    PieSteeringWorld = World;
    PieSteeringController = PlayerController;
    PieSteeringPawn = Pawn;
    PlayerController->StopMovement();
    const TWeakObjectPtr<UWorld> WeakWorld(World);
    const TWeakObjectPtr<APlayerController> WeakController(PlayerController);
    const TWeakObjectPtr<APawn> WeakPawn(Pawn);
    const TWeakObjectPtr<AActor> WeakTarget(TargetActor);
    const bool bTrackActor = TargetActor != nullptr;
    const TSharedRef<FDccMcpInputSteeringState> SteeringState =
        MakeShareable(new FDccMcpInputSteeringState(MoveTemp(Waypoints)));
    PieInputSteeringTickerHandle = FDccMcpCoreTicker::GetCoreTicker().AddTicker(
        FTickerDelegate::CreateLambda(
            [WeakWorld, WeakController, WeakPawn, WeakTarget, bTrackActor, TargetLocation, SteeringState](float)
            {
                APlayerController* Controller = WeakController.Get();
                APawn* ControlledPawn = WeakPawn.Get();
                const auto IsBoundContext = [WeakWorld, WeakController, WeakPawn]()
                {
                    UWorld* OwnedWorld = WeakWorld.Get();
                    APlayerController* OwnedController = WeakController.Get();
                    APawn* OwnedPawn = WeakPawn.Get();
                    return IsInGameThread() && OwnedWorld && IsPlayableWorld(OwnedWorld)
                        && OwnedController && OwnedController->IsLocalController() && OwnedPawn
                        && OwnedController->GetWorld() == OwnedWorld && OwnedPawn->GetWorld() == OwnedWorld
                        && OwnedController->GetPawn() == OwnedPawn;
                };
                if (!IsBoundContext())
                {
                    return false;
                }

                FVector CurrentTarget = TargetLocation;
                if (bTrackActor)
                {
                    AActor* Target = WeakTarget.Get();
                    if (!Target || ControlledPawn->GetWorld() != Target->GetWorld())
                    {
                        return false;
                    }
                    CurrentTarget = Target->GetActorLocation();
                    SteeringState->Waypoints.Last() = CurrentTarget;
                }

                const FVector PawnLocation = ControlledPawn->GetActorLocation();
                while (SteeringState->WaypointIndex < SteeringState->Waypoints.Num() - 1
                    && FVector::DistSquared2D(
                           PawnLocation,
                           SteeringState->Waypoints[SteeringState->WaypointIndex]
                       )
                        <= FMath::Square(100.0f))
                {
                    ++SteeringState->WaypointIndex;
                }
                const FVector SteeringTarget = SteeringState->WaypointIndex < SteeringState->Waypoints.Num()
                    ? SteeringState->Waypoints[SteeringState->WaypointIndex]
                    : CurrentTarget;
                FVector Direction = SteeringTarget - PawnLocation;
                Direction.Z = 0.0f;
                if (!Direction.Normalize())
                {
                    return true;
                }
                const FRotator CurrentRotation = Controller->GetControlRotation();
                if (!IsBoundContext())
                {
                    return false;
                }
                Controller->SetControlRotation(FRotator(CurrentRotation.Pitch, Direction.Rotation().Yaw, 0.0f));
                if (!IsBoundContext())
                {
                    return false;
                }
                ControlledPawn->AddMovementInput(Direction, 1.0f, false);
                return true;
            }
        )
    );
    return PieInputSteeringTickerHandle.IsValid();
}

bool InjectPlayerInput(APlayerController* PlayerController, const FKey& Key, EInputEvent Event, float Value)
{
    if (!PlayerController || !PlayerController->PlayerInput)
    {
        return false;
    }
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    const FInputDeviceId InputDevice = IPlatformInputDeviceMapper::Get().GetPrimaryInputDeviceForUser(
        PlayerController->GetPlatformUserId()
    );
    if (Event == IE_Axis)
    {
        constexpr float AxisDeltaTime = 1.0f / 60.0f;
        PlayerController->InputKey(
            FInputKeyParams(Key, static_cast<double>(Value), AxisDeltaTime, 1, false, InputDevice)
        );
    }
    else
    {
        PlayerController->InputKey(FInputKeyParams(Key, Event, static_cast<double>(Value), false, InputDevice));
    }
#else
    PlayerController->InputKey(Key, Event, Value, false);
#endif
    // UPlayerInput returns whether an action mapping consumed the event, not
    // whether the key state was updated. Axis-only digital mappings (for
    // example, strafe keys) legitimately return false after accepting input.
    return true;
}

bool CanInjectSlatePieInput()
{
    // UI-only and traveling PIE sessions may not expose GEditor->PlayWorld even
    // though an authoritative PIE world context is already active.
    return IsInGameThread() && HasPieWorld() && FSlateApplication::IsInitialized();
}

bool InjectSlatePieMouseButton(const FKey& Key, bool bPressed, const FVector2D& CursorPosition)
{
    FSlateApplication& SlateApplication = FSlateApplication::Get();
    const TSharedPtr<SWindow> ActiveWindow = SlateApplication.GetActiveTopLevelWindow();
    if (!ActiveWindow.IsValid() || !ActiveWindow->GetNativeWindow().IsValid())
    {
        return false;
    }

    TSet<FKey> PressedButtons;
    if (bPressed)
    {
        PressedButtons.Add(Key);
    }
    FPointerEvent MouseEvent(
        0,
        CursorPosition,
        CursorPosition,
        PressedButtons,
        Key,
        0.0f,
        FModifierKeysState()
    );
    return bPressed
        ? SlateApplication.ProcessMouseButtonDownEvent(ActiveWindow->GetNativeWindow(), MouseEvent)
        : SlateApplication.ProcessMouseButtonUpEvent(MouseEvent);
}

bool InjectSlatePieKey(const FKey& Key, bool bPressed)
{
    if (!CanInjectSlatePieInput())
    {
        return false;
    }

    FSlateApplication& SlateApplication = FSlateApplication::Get();
    if (Key.IsMouseButton())
    {
        return InjectSlatePieMouseButton(Key, bPressed, SlateApplication.GetCursorPos());
    }

    FKeyEvent KeyEvent(Key, FModifierKeysState(), 0, false, 0, 0);
    return bPressed
        ? SlateApplication.ProcessKeyDownEvent(KeyEvent)
        : SlateApplication.ProcessKeyUpEvent(KeyEvent);
}

FString NiagaraAuthoringError(const FString& ErrorCode, const FString& Message, bool bRollbackCompleted = true)
{
    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), false);
    Root->SetStringField(TEXT("error_code"), ErrorCode);
    Root->SetStringField(TEXT("message"), Message);
    Root->SetBoolField(TEXT("rollback_completed"), bRollbackCompleted);
    return SerializeJson(Root);
}

FString NiagaraAuthoringPreflight()
{
#if ENGINE_MAJOR_VERSION < 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION < 8)
    return NiagaraAuthoringError(
        TEXT("niagara_authoring_unsupported"),
        TEXT("Niagara semantic authoring requires Unreal Engine 5.8 or newer")
    );
#else
    if (!IsInGameThread())
    {
        return NiagaraAuthoringError(
            TEXT("niagara_wrong_thread"),
            TEXT("Niagara semantic authoring must run on the Unreal game thread")
        );
    }
    if (!GIsEditor || IsRunningCommandlet() || !FSlateApplication::IsInitialized())
    {
        return NiagaraAuthoringError(
            TEXT("niagara_editor_unavailable"),
            TEXT("Niagara semantic authoring requires a fully loaded interactive Unreal Editor with Slate")
        );
    }
    const TSharedPtr<IPlugin> NiagaraPlugin = IPluginManager::Get().FindPlugin(TEXT("Niagara"));
    if (!NiagaraPlugin.IsValid() || !NiagaraPlugin->IsEnabled())
    {
        return NiagaraAuthoringError(
            TEXT("niagara_plugin_unavailable"),
            TEXT("The Niagara plugin must be enabled before semantic authoring")
        );
    }
    return FString();
#endif
}

#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 8)
constexpr TCHAR DefaultEmptyNiagaraEmitterPath[] =
    TEXT("/Niagara/DefaultAssets/Templates/CascadeConversion/CompletelyEmpty.CompletelyEmpty");
constexpr int32 MaxNiagaraSpecificationChars = 4 * 1024 * 1024;
constexpr int32 MaxNiagaraModules = 2048;
constexpr int32 MaxNiagaraRenderers = 512;
constexpr int32 MaxNiagaraInputs = 4096;

struct FDccMcpNiagaraInputSpec
{
    FName Name;
    FNiagaraExt_StackInputValue Value;
};

struct FDccMcpNiagaraModuleSpec
{
    FString Name;
    FName ScriptName;
    TObjectPtr<UNiagaraScript> Asset = nullptr;
    TArray<FDccMcpNiagaraInputSpec> Inputs;
};

struct FDccMcpNiagaraRendererSpec
{
    FString Name;
    TSubclassOf<UNiagaraRendererProperties> RendererClass;
    FString PropertiesJson;
};

struct FDccMcpNiagaraEmitterSpec
{
    FName Name;
    TObjectPtr<UNiagaraEmitter> Template = nullptr;
    TArray<FDccMcpNiagaraModuleSpec> Modules;
    TArray<FDccMcpNiagaraRendererSpec> Renderers;
};

bool TryGetFiniteNumber(const TSharedPtr<FJsonValue>& Value, double& OutNumber)
{
    if (!Value.IsValid() || Value->Type != EJson::Number)
    {
        return false;
    }
    OutNumber = Value->AsNumber();
    return FMath::IsFinite(OutNumber);
}

bool TryGetFiniteFloat(const TSharedPtr<FJsonValue>& Value, double& OutNumber)
{
    return TryGetFiniteNumber(Value, OutNumber) && FMath::Abs(OutNumber) <= static_cast<double>(MAX_flt);
}

bool TryGetFiniteVector(
    const TSharedPtr<FJsonValue>& Value,
    int32 MinSize,
    int32 MaxSize,
    TArray<double>& OutValues
)
{
    if (!Value.IsValid() || Value->Type != EJson::Array)
    {
        return false;
    }
    const TArray<TSharedPtr<FJsonValue>>& Values = Value->AsArray();
    if (Values.Num() < MinSize || Values.Num() > MaxSize)
    {
        return false;
    }
    OutValues.Reset(Values.Num());
    for (const TSharedPtr<FJsonValue>& Item : Values)
    {
        double Number = 0.0;
        if (!TryGetFiniteFloat(Item, Number))
        {
            return false;
        }
        OutValues.Add(Number);
    }
    return true;
}

template <typename TValue>
bool InitializeNiagaraCoreStructValue(
    const TCHAR* StructPath,
    const TValue& Value,
    FNiagaraExt_StackInputValue& OutValue,
    FString& OutError
)
{
    UScriptStruct* ScriptStruct = LoadObject<UScriptStruct>(nullptr, StructPath);
    if (!ScriptStruct)
    {
        OutError = FString::Printf(TEXT("Niagara input struct '%s' is unavailable"), StructPath);
        return false;
    }
    OutValue.InitializeAs(ScriptStruct, reinterpret_cast<const uint8*>(&Value));
    return true;
}

bool BuildNiagaraInputValue(
    const TSharedPtr<FJsonObject>& InputObject,
    FNiagaraExt_StackInputValue& OutValue,
    FString& OutError
)
{
    FString Type;
    const TSharedPtr<FJsonValue> RawValue = InputObject.IsValid()
        ? InputObject->TryGetField(TEXT("value"))
        : nullptr;
    if (!InputObject.IsValid() || !InputObject->TryGetStringField(TEXT("type"), Type)
        || !RawValue.IsValid())
    {
        OutError = TEXT("Every module input requires type and value fields");
        return false;
    }

    if (Type == TEXT("float"))
    {
        double Number = 0.0;
        if (!TryGetFiniteFloat(RawValue, Number))
        {
            OutError = TEXT("float input values must be finite numbers");
            return false;
        }
        OutValue.InitializeAs<FNiagaraFloat>().Value = static_cast<float>(Number);
        return true;
    }
    if (Type == TEXT("int"))
    {
        double Number = 0.0;
        if (!TryGetFiniteNumber(RawValue, Number) || Number != FMath::TruncToDouble(Number)
            || Number < static_cast<double>(MIN_int32) || Number > static_cast<double>(MAX_int32))
        {
            OutError = TEXT("int input values must be integral 32-bit numbers");
            return false;
        }
        OutValue.InitializeAs<FNiagaraInt32>().Value = static_cast<int32>(Number);
        return true;
    }
    if (Type == TEXT("bool"))
    {
        if (RawValue->Type != EJson::Boolean)
        {
            OutError = TEXT("bool input values must be JSON booleans");
            return false;
        }
        OutValue.InitializeAs<FNiagaraBool>().SetValue(RawValue->AsBool());
        return true;
    }

    TArray<double> Values;
    if (Type == TEXT("vector2"))
    {
        if (!TryGetFiniteVector(RawValue, 2, 2, Values))
        {
            OutError = TEXT("vector2 input values must contain two finite numbers");
            return false;
        }
        const FVector2f VectorValue(static_cast<float>(Values[0]), static_cast<float>(Values[1]));
        return InitializeNiagaraCoreStructValue(
            TEXT("/Script/CoreUObject.Vector2f"), VectorValue, OutValue, OutError
        );
    }
    if (Type == TEXT("vector3"))
    {
        if (!TryGetFiniteVector(RawValue, 3, 3, Values))
        {
            OutError = TEXT("vector3 input values must contain three finite numbers");
            return false;
        }
        const FVector3f VectorValue(
            static_cast<float>(Values[0]),
            static_cast<float>(Values[1]),
            static_cast<float>(Values[2])
        );
        return InitializeNiagaraCoreStructValue(
            TEXT("/Script/CoreUObject.Vector3f"), VectorValue, OutValue, OutError
        );
    }
    if (Type == TEXT("color"))
    {
        if (!TryGetFiniteVector(RawValue, 3, 4, Values))
        {
            OutError = TEXT("color input values must contain three or four finite numbers");
            return false;
        }
        OutValue.InitializeAs<FLinearColor>(
            static_cast<float>(Values[0]),
            static_cast<float>(Values[1]),
            static_cast<float>(Values[2]),
            Values.Num() == 4 ? static_cast<float>(Values[3]) : 1.0f
        );
        return true;
    }
    if (Type == TEXT("enum"))
    {
        FString EnumPath;
        FString EnumName;
        if (!InputObject->TryGetStringField(TEXT("enum_path"), EnumPath)
            || RawValue->Type != EJson::String)
        {
            OutError = TEXT("enum input values require enum_path and a string value");
            return false;
        }
        EnumName = RawValue->AsString();
        UEnum* Enum = LoadObject<UEnum>(nullptr, *EnumPath);
        if (!Enum || Enum->GetIndexByNameString(EnumName) == INDEX_NONE)
        {
            OutError = FString::Printf(TEXT("enum value '%s' was not found in '%s'"), *EnumName, *EnumPath);
            return false;
        }
        FNiagaraExt_StackInputData_Enum& EnumValue = OutValue.InitializeAs<FNiagaraExt_StackInputData_Enum>();
        EnumValue.Enum = Enum;
        EnumValue.EnumName = FName(*EnumName);
        EnumValue.DisplayName = Enum->GetDisplayNameTextByIndex(Enum->GetIndexByNameString(EnumName));
        return true;
    }

    OutError = FString::Printf(TEXT("unsupported Niagara input type '%s'"), *Type);
    return false;
}

bool ParseNiagaraAuthoringSpec(
    const TSharedRef<FJsonObject>& Root,
    FString& OutAssetName,
    FString& OutAssetPath,
    TArray<FDccMcpNiagaraEmitterSpec>& OutEmitters,
    FString& OutError
)
{
    if (!Root->TryGetStringField(TEXT("asset_name"), OutAssetName)
        || OutAssetName.IsEmpty() || OutAssetName != FPackageName::GetShortName(OutAssetName))
    {
        OutError = TEXT("asset_name must be a simple non-empty Unreal asset name");
        return false;
    }
    if (!Root->TryGetStringField(TEXT("asset_path"), OutAssetPath)
        || !FPackageName::IsValidLongPackageName(OutAssetPath)
        || !(OutAssetPath == TEXT("/Game") || OutAssetPath.StartsWith(TEXT("/Game/"))))
    {
        OutError = TEXT("asset_path must be /Game or a valid package folder below /Game");
        return false;
    }
    if (!FPackageName::IsValidLongPackageName(OutAssetPath / OutAssetName))
    {
        OutError = TEXT("asset_name contains characters that are invalid in an Unreal package");
        return false;
    }

    const TArray<TSharedPtr<FJsonValue>>* EmitterValues = nullptr;
    if (!Root->TryGetArrayField(TEXT("emitters"), EmitterValues) || !EmitterValues
        || EmitterValues->Num() == 0 || EmitterValues->Num() > 128)
    {
        OutError = TEXT("emitters must contain between 1 and 128 emitter specifications");
        return false;
    }

    TSet<FName> EmitterNames;
    int32 TotalModuleCount = 0;
    int32 TotalRendererCount = 0;
    int32 TotalInputCount = 0;
    for (const TSharedPtr<FJsonValue>& EmitterValue : *EmitterValues)
    {
        const TSharedPtr<FJsonObject> EmitterObject = EmitterValue.IsValid() && EmitterValue->Type == EJson::Object
            ? EmitterValue->AsObject()
            : nullptr;
        FString EmitterName;
        FString TemplatePath = DefaultEmptyNiagaraEmitterPath;
        if (!EmitterObject.IsValid() || !EmitterObject->TryGetStringField(TEXT("name"), EmitterName)
            || EmitterName.IsEmpty())
        {
            OutError = TEXT("every emitter requires a non-empty name");
            return false;
        }
        const FName EmitterFName(*EmitterName);
        if (EmitterNames.Contains(EmitterFName))
        {
            OutError = FString::Printf(TEXT("duplicate emitter name '%s'"), *EmitterName);
            return false;
        }
        EmitterNames.Add(EmitterFName);
        EmitterObject->TryGetStringField(TEXT("template_path"), TemplatePath);
        UNiagaraEmitter* Template = LoadObject<UNiagaraEmitter>(nullptr, *TemplatePath);
        if (!Template)
        {
            OutError = FString::Printf(TEXT("Niagara emitter template was not found: %s"), *TemplatePath);
            return false;
        }

        const TArray<TSharedPtr<FJsonValue>>* ModuleValues = nullptr;
        const TArray<TSharedPtr<FJsonValue>>* RendererValues = nullptr;
        if (!EmitterObject->TryGetArrayField(TEXT("modules"), ModuleValues) || !ModuleValues
            || ModuleValues->Num() > 256)
        {
            OutError = FString::Printf(TEXT("emitter '%s' modules must be an array of at most 256 entries"), *EmitterName);
            return false;
        }
        if (!EmitterObject->TryGetArrayField(TEXT("renderers"), RendererValues) || !RendererValues
            || RendererValues->Num() == 0 || RendererValues->Num() > 16)
        {
            OutError = FString::Printf(TEXT("emitter '%s' renderers must contain between 1 and 16 entries"), *EmitterName);
            return false;
        }
        TotalModuleCount += ModuleValues->Num();
        TotalRendererCount += RendererValues->Num();
        if (TotalModuleCount > MaxNiagaraModules || TotalRendererCount > MaxNiagaraRenderers)
        {
            OutError = TEXT("the Niagara specification exceeds the total module or renderer safety limit");
            return false;
        }

        FDccMcpNiagaraEmitterSpec EmitterSpec;
        EmitterSpec.Name = EmitterFName;
        EmitterSpec.Template = Template;
        for (const TSharedPtr<FJsonValue>& ModuleValue : *ModuleValues)
        {
            const TSharedPtr<FJsonObject> ModuleObject = ModuleValue.IsValid() && ModuleValue->Type == EJson::Object
                ? ModuleValue->AsObject()
                : nullptr;
            FString ModuleName;
            FString Script;
            FString AssetPath;
            if (!ModuleObject.IsValid() || !ModuleObject->TryGetStringField(TEXT("name"), ModuleName)
                || ModuleName.IsEmpty() || !ModuleObject->TryGetStringField(TEXT("script"), Script)
                || !ModuleObject->TryGetStringField(TEXT("asset_path"), AssetPath) || AssetPath.IsEmpty())
            {
                OutError = FString::Printf(TEXT("emitter '%s' has an invalid module specification"), *EmitterName);
                return false;
            }
            static const TMap<FString, FName> ScriptNames = {
                {TEXT("emitter_spawn"), TEXT("EmitterSpawnScript")},
                {TEXT("emitter_update"), TEXT("EmitterUpdateScript")},
                {TEXT("particle_spawn"), TEXT("ParticleSpawnScript")},
                {TEXT("particle_update"), TEXT("ParticleUpdateScript")},
            };
            const FName* ScriptName = ScriptNames.Find(Script);
            UNiagaraScript* ModuleAsset = LoadObject<UNiagaraScript>(nullptr, *AssetPath);
            if (!ScriptName || !ModuleAsset)
            {
                OutError = FString::Printf(
                    TEXT("module '%s' has an unsupported script or missing asset '%s'"),
                    *ModuleName,
                    *AssetPath
                );
                return false;
            }

            FDccMcpNiagaraModuleSpec ModuleSpec;
            ModuleSpec.Name = ModuleName;
            ModuleSpec.ScriptName = *ScriptName;
            ModuleSpec.Asset = ModuleAsset;
            const TSharedPtr<FJsonObject>* InputsObject = nullptr;
            if (ModuleObject->TryGetObjectField(TEXT("inputs"), InputsObject) && InputsObject && InputsObject->IsValid())
            {
                TotalInputCount += (*InputsObject)->Values.Num();
                if ((*InputsObject)->Values.Num() > 128 || TotalInputCount > MaxNiagaraInputs)
                {
                    OutError = TEXT("the Niagara specification exceeds the input safety limit");
                    return false;
                }
                for (const TPair<FString, TSharedPtr<FJsonValue>>& InputPair : (*InputsObject)->Values)
                {
                    const TSharedPtr<FJsonObject> InputObject = InputPair.Value.IsValid()
                        && InputPair.Value->Type == EJson::Object
                        ? InputPair.Value->AsObject()
                        : nullptr;
                    FDccMcpNiagaraInputSpec InputSpec;
                    InputSpec.Name = FName(*InputPair.Key);
                    FString InputError;
                    if (InputPair.Key.IsEmpty() || !BuildNiagaraInputValue(InputObject, InputSpec.Value, InputError))
                    {
                        OutError = FString::Printf(
                            TEXT("module '%s' input '%s' is invalid: %s"),
                            *ModuleName,
                            *InputPair.Key,
                            *InputError
                        );
                        return false;
                    }
                    ModuleSpec.Inputs.Add(MoveTemp(InputSpec));
                }
            }
            EmitterSpec.Modules.Add(MoveTemp(ModuleSpec));
        }

        for (const TSharedPtr<FJsonValue>& RendererValue : *RendererValues)
        {
            const TSharedPtr<FJsonObject> RendererObject = RendererValue.IsValid()
                && RendererValue->Type == EJson::Object
                ? RendererValue->AsObject()
                : nullptr;
            FString RendererName;
            FString ClassPath = TEXT("/Script/Niagara.NiagaraSpriteRendererProperties");
            if (!RendererObject.IsValid() || !RendererObject->TryGetStringField(TEXT("name"), RendererName)
                || RendererName.IsEmpty())
            {
                OutError = FString::Printf(TEXT("emitter '%s' has an invalid renderer specification"), *EmitterName);
                return false;
            }
            RendererObject->TryGetStringField(TEXT("class_path"), ClassPath);
            UClass* RendererClass = LoadObject<UClass>(nullptr, *ClassPath);
            if (!RendererClass || !RendererClass->IsChildOf(UNiagaraRendererProperties::StaticClass()))
            {
                OutError = FString::Printf(TEXT("renderer class was not found or is not a Niagara renderer: %s"), *ClassPath);
                return false;
            }

            FDccMcpNiagaraRendererSpec RendererSpec;
            RendererSpec.Name = RendererName;
            RendererSpec.RendererClass = RendererClass;
            const TSharedPtr<FJsonObject>* PropertiesObject = nullptr;
            if (RendererObject->TryGetObjectField(TEXT("properties"), PropertiesObject)
                && PropertiesObject && PropertiesObject->IsValid() && (*PropertiesObject)->Values.Num() > 0)
            {
                RendererSpec.PropertiesJson = SerializeJson((*PropertiesObject).ToSharedRef());
            }
            EmitterSpec.Renderers.Add(MoveTemp(RendererSpec));
        }
        OutEmitters.Add(MoveTemp(EmitterSpec));
    }
    return true;
}

FString NiagaraContextError(const FNiagaraExternalEditContext& Context)
{
    TArray<FString> Messages;
    for (const FText& Error : Context.Errors)
    {
        Messages.Add(Error.ToString());
    }
    return Messages.Num() > 0 ? FString::Join(Messages, TEXT("; ")) : TEXT("Niagara external editor operation failed");
}

bool RollbackNiagaraSystem(UNiagaraSystem* System, const FString& Filename)
{
    bool bDeletedObject = true;
    if (System)
    {
        TArray<UObject*> ObjectsToDelete{System};
        bDeletedObject = ObjectTools::DeleteObjectsUnchecked(ObjectsToDelete) == 1;
    }
    const bool bDeletedFile = !IFileManager::Get().FileExists(*Filename)
        || IFileManager::Get().Delete(*Filename, false, true, true);
    return bDeletedObject && bDeletedFile;
}
#endif
} // namespace

TArray<FString> UDccMcpAutomationLibrary::GetEnabledPluginNames()
{
    TArray<FString> Names;
    for (const TSharedRef<IPlugin>& Plugin : IPluginManager::Get().GetEnabledPlugins())
    {
        Names.Add(Plugin->GetName());
    }
    Names.Sort();
    return Names;
}

FString UDccMcpAutomationLibrary::AuthorNiagaraSystemJson(const FString& SpecificationJson)
{
    const FString PreflightError = NiagaraAuthoringPreflight();
    if (!PreflightError.IsEmpty())
    {
        return PreflightError;
    }

#if ENGINE_MAJOR_VERSION < 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION < 8)
    return NiagaraAuthoringError(
        TEXT("niagara_authoring_unsupported"),
        TEXT("Niagara semantic authoring requires Unreal Engine 5.8 or newer")
    );
#else
    if (SpecificationJson.Len() > MaxNiagaraSpecificationChars)
    {
        return NiagaraAuthoringError(
            TEXT("invalid_niagara_specification"),
            TEXT("The Niagara authoring specification exceeds the 4-million-character safety limit")
        );
    }
    TSharedPtr<FJsonObject> Specification;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(SpecificationJson);
    if (!FJsonSerializer::Deserialize(Reader, Specification) || !Specification.IsValid())
    {
        return NiagaraAuthoringError(
            TEXT("invalid_niagara_specification"),
            TEXT("The Niagara authoring specification must be a valid JSON object")
        );
    }

    FString AssetName;
    FString AssetPath;
    FString ParseError;
    TArray<FDccMcpNiagaraEmitterSpec> Emitters;
    if (!ParseNiagaraAuthoringSpec(Specification.ToSharedRef(), AssetName, AssetPath, Emitters, ParseError))
    {
        return NiagaraAuthoringError(TEXT("invalid_niagara_specification"), ParseError);
    }

    const FString PackageName = AssetPath / AssetName;
    const FString ObjectPath = PackageName + TEXT(".") + AssetName;
    const FString Filename = FPackageName::LongPackageNameToFilename(
        PackageName,
        FPackageName::GetAssetPackageExtension()
    );
    if (FindObject<UNiagaraSystem>(nullptr, *ObjectPath) || FPackageName::DoesPackageExist(PackageName))
    {
        return NiagaraAuthoringError(
            TEXT("niagara_asset_exists"),
            FString::Printf(TEXT("A Niagara system already exists at '%s'"), *PackageName)
        );
    }
    if (!FModuleManager::Get().IsModuleLoaded(TEXT("NiagaraEditor"))
        && !FModuleManager::Get().LoadModulePtr<IModuleInterface>(TEXT("NiagaraEditor")))
    {
        return NiagaraAuthoringError(
            TEXT("niagara_editor_unavailable"),
            TEXT("The NiagaraEditor module could not be loaded in the current Editor")
        );
    }

    FScopedTransaction Transaction(
        NSLOCTEXT("DccMcpUnreal", "AuthorNiagaraSystem", "DCC MCP Author Niagara System")
    );
    FNiagaraExternalEditContext CreateContext;
    UNiagaraSystem* System = UNiagaraExternalEditUtilities::CreateNiagaraSystem(
        AssetName,
        AssetPath,
        nullptr,
        CreateContext
    );
    if (!System || CreateContext.HasErrors())
    {
        Transaction.Cancel();
        const bool bRolledBack = RollbackNiagaraSystem(System, Filename);
        return NiagaraAuthoringError(
            TEXT("niagara_system_create_failed"),
            CreateContext.HasErrors()
                ? NiagaraContextError(CreateContext)
                : TEXT("UE 5.8 returned no Niagara system"),
            bRolledBack
        );
    }

    const auto FailAndRollback = [System, Filename, &Transaction](
        const FString& ErrorCode,
        const FString& Message
    )
    {
        Transaction.Cancel();
        return NiagaraAuthoringError(ErrorCode, Message, RollbackNiagaraSystem(System, Filename));
    };

    int32 ExpectedModuleCount = 0;
    int32 ExpectedRendererCount = 0;
    FNiagaraExternalEditContext EditContext(System);
    for (const FDccMcpNiagaraEmitterSpec& EmitterSpec : Emitters)
    {
        FNiagaraExt_EmitterTopology AddedEmitter;
        UNiagaraExternalEditUtilities::AddEmitter(
            EmitterSpec.Template,
            EmitterSpec.Name,
            AddedEmitter,
            EditContext
        );
        if (EditContext.HasErrors() || AddedEmitter.EmitterName.IsNone())
        {
            return FailAndRollback(TEXT("niagara_emitter_add_failed"), NiagaraContextError(EditContext));
        }

        for (const FDccMcpNiagaraModuleSpec& ModuleSpec : EmitterSpec.Modules)
        {
            FNiagaraExt_StackItemReference ModuleLocation(
                System,
                AddedEmitter.EmitterName,
                ModuleSpec.ScriptName
            );
            FNiagaraExt_ModuleTopology AddedModule;
            UNiagaraExternalEditUtilities::AddModule(
                ModuleLocation,
                ModuleSpec.Asset,
                AddedModule,
                EditContext
            );
            if (EditContext.HasErrors() || AddedModule.ModuleName.IsNone())
            {
                return FailAndRollback(
                    TEXT("niagara_module_add_failed"),
                    FString::Printf(TEXT("module '%s': %s"), *ModuleSpec.Name, *NiagaraContextError(EditContext))
                );
            }
            ++ExpectedModuleCount;

            for (const FDccMcpNiagaraInputSpec& InputSpec : ModuleSpec.Inputs)
            {
                FNiagaraExt_StackItemReference InputReference(
                    System,
                    AddedEmitter.EmitterName,
                    ModuleSpec.ScriptName,
                    AddedModule.ModuleName
                );
                InputReference.InputNameStack.Add(InputSpec.Name);
                UNiagaraExternalEditUtilities::SetStackInputData(
                    InputReference,
                    InputSpec.Value,
                    EditContext
                );
                if (EditContext.HasErrors())
                {
                    return FailAndRollback(
                        TEXT("niagara_input_set_failed"),
                        FString::Printf(
                            TEXT("module '%s' input '%s': %s"),
                            *ModuleSpec.Name,
                            *InputSpec.Name.ToString(),
                            *NiagaraContextError(EditContext)
                        )
                    );
                }
            }
        }

        for (const FDccMcpNiagaraRendererSpec& RendererSpec : EmitterSpec.Renderers)
        {
            FNiagaraExt_StackItemReference RendererLocation(System, AddedEmitter.EmitterName);
            FNiagaraExt_RendererRef AddedRenderer;
            UNiagaraExternalEditUtilities::AddRenderer(
                RendererLocation,
                RendererSpec.RendererClass,
                AddedRenderer,
                EditContext
            );
            if (EditContext.HasErrors() || AddedRenderer.RendererIndex == INDEX_NONE)
            {
                return FailAndRollback(
                    TEXT("niagara_renderer_add_failed"),
                    FString::Printf(TEXT("renderer '%s': %s"), *RendererSpec.Name, *NiagaraContextError(EditContext))
                );
            }
            ++ExpectedRendererCount;

            if (!RendererSpec.PropertiesJson.IsEmpty())
            {
                FNiagaraExt_StackItemReference RendererReference(System, AddedEmitter.EmitterName);
                RendererReference.RendererIndex = AddedRenderer.RendererIndex;
                FNiagaraExt_RendererData RendererData;
                RendererData.PropertyValues = RendererSpec.PropertiesJson;
                UNiagaraExternalEditUtilities::SetRendererData(RendererReference, RendererData, EditContext);
                if (EditContext.HasErrors())
                {
                    return FailAndRollback(
                        TEXT("niagara_renderer_configure_failed"),
                        FString::Printf(
                            TEXT("renderer '%s': %s"),
                            *RendererSpec.Name,
                            *NiagaraContextError(EditContext)
                        )
                    );
                }
            }
        }
    }

    System->MarkPackageDirty();
    if (!SaveAssetPackage(System, Filename))
    {
        return FailAndRollback(
            TEXT("niagara_save_failed"),
            TEXT("Unreal failed to save the authored Niagara system")
        );
    }

    FNiagaraExternalEditContext VerifyContext(System);
    FNiagaraExt_SystemSummary Summary;
    UNiagaraExternalEditUtilities::GetSystemSummary(System, Summary, VerifyContext);
    int32 ActualModuleCount = 0;
    int32 ActualRendererCount = 0;
    for (const FDccMcpNiagaraEmitterSpec& EmitterSpec : Emitters)
    {
        FNiagaraExt_StackItemReference EmitterReference(System, EmitterSpec.Name);
        FNiagaraExt_EmitterTopology Topology;
        UNiagaraExternalEditUtilities::GetEmitterTopology(EmitterReference, Topology, VerifyContext);
        ActualModuleCount += Topology.EmitterSpawnScript.Modules.Num();
        ActualModuleCount += Topology.EmitterUpdateScript.Modules.Num();
        ActualModuleCount += Topology.ParticleSpawnScript.Modules.Num();
        ActualModuleCount += Topology.ParticleUpdateScript.Modules.Num();
        ActualRendererCount += Topology.Renderers.Num();
    }
    UPackage* Package = System->GetOutermost();
    const bool bVerified = !VerifyContext.HasErrors()
        && Summary.Emitters.Num() == Emitters.Num()
        && ActualModuleCount >= ExpectedModuleCount
        && ActualRendererCount >= ExpectedRendererCount
        && Package && !Package->IsDirty()
        && FindObject<UNiagaraSystem>(nullptr, *ObjectPath) == System;
    if (!bVerified)
    {
        return FailAndRollback(
            TEXT("niagara_postcondition_failed"),
            VerifyContext.HasErrors()
                ? NiagaraContextError(VerifyContext)
                : TEXT("The saved Niagara topology did not contain every requested emitter, module, and renderer")
        );
    }

    TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
    Result->SetBoolField(TEXT("success"), true);
    Result->SetStringField(TEXT("message"), FString::Printf(TEXT("Authored Niagara system '%s'"), *PackageName));
    Result->SetStringField(TEXT("system_path"), PackageName);
    Result->SetNumberField(TEXT("emitter_count"), Summary.Emitters.Num());
    Result->SetNumberField(TEXT("module_count"), ActualModuleCount);
    Result->SetNumberField(TEXT("renderer_count"), ActualRendererCount);
    Result->SetBoolField(TEXT("saved"), true);
    Result->SetBoolField(TEXT("verified"), true);
    return SerializeJson(Result);
#endif
}

FString UDccMcpAutomationLibrary::ListAutomationTestsJson(const FString& Filter)
{
    FAutomationTestFramework& Framework = FAutomationTestFramework::Get();
    Framework.LoadTestModules();
#if ENGINE_MAJOR_VERSION < 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION < 5)
    Framework.SetRequestedTestFilter(EAutomationTestFlags::FilterMask);
#else
    Framework.SetRequestedTestFilter(EAutomationTestFlags_FilterMask);
#endif

    TArray<FAutomationTestInfo> TestInfo;
    Framework.GetValidTestNames(TestInfo);

    TArray<TSharedPtr<FJsonValue>> Tests;
    for (const FAutomationTestInfo& Info : TestInfo)
    {
        const FString TestName = Info.GetTestName();
        const FString FullPath = Info.GetFullTestPath();
        const FString DisplayName = Info.GetDisplayName();
        if (!Filter.IsEmpty() && !TestName.Contains(Filter) && !FullPath.Contains(Filter) && !DisplayName.Contains(Filter))
        {
            continue;
        }

        TSharedRef<FJsonObject> Test = MakeShared<FJsonObject>();
        Test->SetStringField(TEXT("name"), TestName);
        Test->SetStringField(TEXT("full_path"), FullPath);
        Test->SetStringField(TEXT("display_name"), DisplayName);
        Test->SetStringField(TEXT("parameter"), Info.GetTestParameter());
        Test->SetStringField(TEXT("source_file"), Info.GetSourceFile());
        Test->SetNumberField(TEXT("source_line"), Info.GetSourceFileLine());
        Test->SetStringField(TEXT("asset_path"), Info.GetAssetPath());
        Test->SetNumberField(TEXT("flags"), static_cast<double>(static_cast<uint32>(Info.GetTestFlags())));
        Tests.Add(MakeShared<FJsonValueObject>(Test));
    }

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("filter"), Filter);
    Root->SetNumberField(TEXT("count"), Tests.Num());
    Root->SetArrayField(TEXT("tests"), Tests);

    return SerializeJson(Root);
}

FString UDccMcpAutomationLibrary::AcquirePieKey(UWorld* World, APlayerController* Controller, const FString& KeyName)
{
    const FKey Key{FName(*KeyName)};
    const TArray<FString> AllowedKeys = {TEXT("W"), TEXT("A"), TEXT("S"), TEXT("D"), TEXT("F"),
        TEXT("LeftMouseButton"), TEXT("RightMouseButton"), TEXT("V"), TEXT("Q"), TEXT("E"),
        TEXT("R"), TEXT("SpaceBar")};
    if (!IsInGameThread() || !IsValid(World) || !IsPlayableWorld(World) || !IsValid(Controller)
        || Controller->GetWorld() != World || !Controller->IsLocalController()
        || !IsValid(Controller->PlayerInput) || !Key.IsValid() || !AllowedKeys.Contains(KeyName))
    {
        return FString();
    }
    for (auto It = OwnedPieKeys.CreateIterator(); It; ++It)
    {
        if (!It.Value().World.IsValid() || !It.Value().Controller.IsValid() || !It.Value().Receiver.IsValid())
        {
            It.RemoveCurrent();
        }
        else if (It.Value().Receiver.Get() == Controller->PlayerInput && It.Value().Key == Key)
        {
            return FString(); // Do not let overlapping actions release each other's input.
        }
    }
    if (OwnedPieKeys.Num() >= 128)
    {
        return FString();
    }
    FDccMcpOwnedKey State;
    State.World = World;
    State.Controller = Controller;
    State.Receiver = Controller->PlayerInput;
    State.Pawn = Controller->GetPawn();
    State.Key = Key;
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    State.Device = IPlatformInputDeviceMapper::Get().GetPrimaryInputDeviceForUser(Controller->GetPlatformUserId());
#endif
    const FString Owner = FGuid::NewGuid().ToString();
    OwnedPieKeys.Add(Owner, State);
    return Owner;
}

bool UDccMcpAutomationLibrary::PressOwnedPieKey(const FString& Owner)
{
    if (!IsInGameThread())
    {
        return false;
    }
    FDccMcpOwnedKey* State = OwnedPieKeys.Find(Owner);
    if (!State || State->bPressAttempted || !State->Controller.IsValid()
        || !State->Pawn.IsValid() || State->Controller->GetPawn() != State->Pawn.Get()
        || State->Controller->PlayerInput != State->Receiver.Get())
    {
        return false;
    }
    State->bPressAttempted = true;
    return DeliverOwnedKey(*State, true);
}

bool UDccMcpAutomationLibrary::ReleaseOwnedPieKey(const FString& Owner)
{
    if (!IsInGameThread())
    {
        return false;
    }
    FDccMcpOwnedKey State;
    if (!OwnedPieKeys.RemoveAndCopyValue(Owner, State))
    {
        return false;
    }
    return !State.bPressAttempted || DeliverOwnedKey(State, false);
}

bool UDccMcpAutomationLibrary::InjectPieKey(const FString& KeyName, bool bPressed)
{
    APlayerController* PlayerController = GetPiePlayerController();
    const FKey Key = FKey(FName(*KeyName));
    if (!Key.IsValid())
    {
        return false;
    }
    if (PlayerController)
    {
        return InjectPlayerInput(PlayerController, Key, bPressed ? IE_Pressed : IE_Released, bPressed ? 1.0f : 0.0f);
    }
    return InjectSlatePieKey(Key, bPressed);
}

bool UDccMcpAutomationLibrary::ClickPiePointerButton(const FString& KeyName, float NormalizedX, float NormalizedY)
{
    const FKey Key = FKey(FName(*KeyName));
    if (!CanInjectSlatePieInput() || !Key.IsValid() || !Key.IsMouseButton()
        || !FMath::IsFinite(NormalizedX) || !FMath::IsFinite(NormalizedY)
        || NormalizedX < 0.0f || NormalizedX > 1.0f || NormalizedY < 0.0f || NormalizedY > 1.0f)
    {
        return false;
    }

    FSlateApplication& SlateApplication = FSlateApplication::Get();
    const TSharedPtr<SWindow> ActiveWindow = SlateApplication.GetActiveTopLevelWindow();
    if (!ActiveWindow.IsValid())
    {
        return false;
    }
    const FVector2D WindowSize = ActiveWindow->GetSizeInScreen();
    if (WindowSize.X <= 0.0f || WindowSize.Y <= 0.0f)
    {
        return false;
    }
    const FVector2D CursorPosition = ActiveWindow->GetPositionInScreen()
        + FVector2D(NormalizedX * WindowSize.X, NormalizedY * WindowSize.Y);

    // Prime Slate's hover path without moving the OS cursor. SButton's default
    // DownAndUp click method requires the button to remain hovered on release.
    // A synthetic positioned click otherwise presses the right widget but does
    // not execute its OnClicked delegate.
    TSet<FKey> HoverButtons;
    FPointerEvent HoverEvent(
        0,
        CursorPosition,
        CursorPosition,
        HoverButtons,
        FKey(),
        0.0f,
        FModifierKeysState()
    );
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26
    const FWidgetPath WidgetsUnderPointer = SlateApplication.LocateWindowUnderMouse(
        CursorPosition,
        SlateApplication.GetInteractiveTopLevelWindows(),
        false
    );
#else
    const FWidgetPath WidgetsUnderPointer = SlateApplication.LocateWindowUnderMouse(
        CursorPosition,
        SlateApplication.GetInteractiveTopLevelWindows(),
        false,
        0
    );
#endif
    if (!WidgetsUnderPointer.IsValid())
    {
        return false;
    }
    SlateApplication.RoutePointerMoveEvent(WidgetsUnderPointer, HoverEvent, true);

    const bool bPressedHandled = InjectSlatePieMouseButton(Key, true, CursorPosition);
    const bool bReleasedHandled = InjectSlatePieMouseButton(Key, false, CursorPosition);
    return bPressedHandled || bReleasedHandled;
}

bool UDccMcpAutomationLibrary::InjectPieAxis(const FString& KeyName, float Value)
{
    APlayerController* PlayerController = GetPiePlayerController();
    const FKey Key = FKey(FName(*KeyName));
    if (!PlayerController || !Key.IsValid())
    {
        return false;
    }
    return InjectPlayerInput(PlayerController, Key, IE_Axis, Value);
}

bool UDccMcpAutomationLibrary::InjectPieLook(float DeltaX, float DeltaY)
{
    APlayerController* PlayerController = GetPiePlayerController();
    if (!PlayerController || !FMath::IsFinite(DeltaX) || !FMath::IsFinite(DeltaY))
    {
        return false;
    }

    // A one-shot raw MouseX/MouseY sample can be cleared before the next
    // ProcessPlayerInput pass when an MCP request is dispatched late in the
    // editor frame. AddController input is the engine's deterministic,
    // possessed-player route and is consumed by the normal controller tick.
    if (!FMath::IsNearlyZero(DeltaX))
    {
        PlayerController->AddYawInput(DeltaX);
    }
    if (!FMath::IsNearlyZero(DeltaY))
    {
        PlayerController->AddPitchInput(-DeltaY);
    }
    return true;
}

bool UDccMcpAutomationLibrary::NavigatePieToActor(const FString& ActorName)
{
    APlayerController* PlayerController = GetPiePlayerController();
    UWorld* World = PlayerController ? PlayerController->GetWorld() : nullptr;
    if (!IsInGameThread() || !PlayerController || !World || ActorName.IsEmpty())
    {
        return false;
    }

    AActor* TargetActor = FindPieActorByName(World, ActorName);
    if (!TargetActor || !PlayerController->GetPawn())
    {
        return false;
    }

#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
    UNavigationSystem::SimpleMoveToActor(PlayerController, TargetActor);
#else
    UAIBlueprintHelperLibrary::SimpleMoveToActor(PlayerController, TargetActor);
#endif
    return true;
}

bool UDccMcpAutomationLibrary::NavigatePieToLocation(const FVector& TargetLocation)
{
    APlayerController* PlayerController = GetPiePlayerController();
    if (!IsInGameThread() || !PlayerController || !PlayerController->GetPawn() || TargetLocation.ContainsNaN())
    {
        return false;
    }

#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
    UNavigationSystem::SimpleMoveToLocation(PlayerController, TargetLocation);
#else
    UAIBlueprintHelperLibrary::SimpleMoveToLocation(PlayerController, TargetLocation);
#endif
    return true;
}

bool UDccMcpAutomationLibrary::StartPieInputSteering(const FString& ActorName)
{
    APlayerController* PlayerController = GetPiePlayerController();
    UWorld* World = PlayerController ? PlayerController->GetWorld() : nullptr;
    APawn* Pawn = PlayerController ? PlayerController->GetPawn() : nullptr;
    if (!IsInGameThread() || !PlayerController || !World || !Pawn || ActorName.IsEmpty())
    {
        return false;
    }

    AActor* TargetActor = FindPieActorByName(World, ActorName);
    if (!TargetActor)
    {
        return false;
    }
    return StartPieInputSteeringInternal(PlayerController->GetWorld(), PlayerController, Pawn, TargetActor->GetActorLocation(), TargetActor);
}

bool UDccMcpAutomationLibrary::StartPieInputSteeringToLocation(const FVector& TargetLocation)
{
    APlayerController* PlayerController = GetPiePlayerController();
    APawn* Pawn = PlayerController ? PlayerController->GetPawn() : nullptr;
    if (!IsInGameThread() || !PlayerController || !Pawn || TargetLocation.ContainsNaN())
    {
        return false;
    }
    return StartPieInputSteeringInternal(PlayerController->GetWorld(), PlayerController, Pawn, TargetLocation, nullptr);
}

static bool IsOwnedPieNavigationContext(UWorld* World, APlayerController* Controller, APawn* Pawn)
{
    return IsInGameThread() && IsValid(World) && IsPlayableWorld(World)
        && IsValid(Controller) && Controller->IsLocalController() && IsValid(Pawn)
        && Controller->GetWorld() == World && Pawn->GetWorld() == World && Controller->GetPawn() == Pawn;
}

static bool IsBoundedPieLocation(const FVector& Location)
{
    return !Location.ContainsNaN() && FMath::Abs(Location.X) <= 1000000.0
        && FMath::Abs(Location.Y) <= 1000000.0 && FMath::Abs(Location.Z) <= 1000000.0;
}

bool UDccMcpAutomationLibrary::NavigateOwnedPieToLocation(UWorld* World, APlayerController* Controller, APawn* Pawn, const FVector& TargetLocation)
{
    if (!IsOwnedPieNavigationContext(World, Controller, Pawn) || !IsBoundedPieLocation(TargetLocation))
    {
        return false;
    }
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
    UNavigationSystem::SimpleMoveToLocation(Controller, TargetLocation);
#else
    UAIBlueprintHelperLibrary::SimpleMoveToLocation(Controller, TargetLocation);
#endif
    return true;
}

bool UDccMcpAutomationLibrary::NavigateOwnedPieToActor(UWorld* World, APlayerController* Controller, APawn* Pawn, AActor* TargetActor)
{
    if (!IsOwnedPieNavigationContext(World, Controller, Pawn) || !IsValid(TargetActor)
        || TargetActor->GetWorld() != World)
    {
        return false;
    }
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 20
    UNavigationSystem::SimpleMoveToActor(Controller, TargetActor);
#else
    UAIBlueprintHelperLibrary::SimpleMoveToActor(Controller, TargetActor);
#endif
    return true;
}

bool UDccMcpAutomationLibrary::StartOwnedPieInputSteeringToLocation(UWorld* World, APlayerController* Controller, APawn* Pawn, const FVector& TargetLocation)
{
    if (!IsOwnedPieNavigationContext(World, Controller, Pawn) || !IsBoundedPieLocation(TargetLocation))
    {
        return false;
    }
    return StartPieInputSteeringInternal(World, Controller, Pawn, TargetLocation, nullptr);
}

bool UDccMcpAutomationLibrary::StopOwnedPieNavigation(UWorld* World, APlayerController* Controller, APawn* Pawn)
{
    if (!IsInGameThread())
    {
        return false;
    }
    if (PieSteeringWorld.Get() == World && PieSteeringController.Get() == Controller && PieSteeringPawn.Get() == Pawn)
    {
        StopPieInputSteeringTicker();
    }
    if (!IsValid(World) || !IsValid(Controller) || !IsValid(Pawn)
        || Controller->GetWorld() != World || Pawn->GetWorld() != World || Controller->GetPawn() != Pawn)
    {
        return false; // Never stop a replacement pawn, even on the original controller.
    }
    Controller->StopMovement();
    return true;
}

bool UDccMcpAutomationLibrary::StopPieNavigation()
{
    APlayerController* PlayerController = GetPiePlayerController();
    if (!IsInGameThread() || !PlayerController)
    {
        return false;
    }
    StopPieInputSteeringTicker();
    PlayerController->StopMovement();
    return true;
}

FString UDccMcpAutomationLibrary::GetFabSessionStatusJson()
{
    const TSharedPtr<IPlugin> FabPlugin = IPluginManager::Get().FindPlugin(FabModuleName);
    UObject* FabApi = NewFabApi();
    FString AuthToken;
    const bool bCanInspect = InvokeFabStringResult(FabApi, TEXT("GetAuthToken"), AuthToken);

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("plugin_available"), FabApi != nullptr && bCanInspect);
    Root->SetBoolField(TEXT("authenticated"), bCanInspect && !AuthToken.IsEmpty());
    Root->SetStringField(TEXT("engine_version"), FString::Printf(TEXT("%d.%d"), ENGINE_MAJOR_VERSION, ENGINE_MINOR_VERSION));
    Root->SetStringField(
        TEXT("plugin_version"), FabPlugin.IsValid() ? FabPlugin->GetDescriptor().VersionName : FString()
    );
    AuthToken.Reset();
    return SerializeJson(Root);
}

bool UDccMcpAutomationLibrary::RequestFabLogin()
{
    return InvokeFabNoArgs(NewFabApi(), TEXT("Login"));
}

bool UDccMcpAutomationLibrary::OpenFabListing(const FString& ListingUrl)
{
    if (!ListingUrl.StartsWith(FabListingPrefix, ESearchCase::CaseSensitive))
    {
        return false;
    }
    return InvokeFabString(NewFabApi(), TEXT("OpenInNewTab"), ListingUrl);
}

FString UDccMcpAutomationLibrary::FocusLevelEditorViewport()
{
    TArray<FString> CloseRequestedItems;
    TArray<FString> ClosedItems;
    TArray<FString> RemainingLogTabs;
    if (!IsInGameThread())
    {
        return EditorViewportFocusResult(
            CloseRequestedItems,
            ClosedItems,
            RemainingLogTabs,
            false,
            false,
            TEXT("wrong_thread"),
            TEXT("Level Editor focus requires the game thread")
        );
    }
    if (!FSlateApplication::IsInitialized())
    {
        return EditorViewportFocusResult(
            CloseRequestedItems,
            ClosedItems,
            RemainingLogTabs,
            false,
            false,
            TEXT("slate_unavailable"),
            TEXT("Slate is not initialized")
        );
    }

    const TArray<FName> LogTabIds = {FName(TEXT("OutputLog")), FName(TEXT("MessageLog"))};
    const TSharedRef<FGlobalTabmanager> TabManager = FGlobalTabmanager::Get();
    for (const FName& TabId : LogTabIds)
    {
        const FTabId LiveTabId(TabId);
        const TSharedPtr<SDockTab> LiveTab = TabManager->FindExistingLiveTab(LiveTabId);
        if (!LiveTab.IsValid())
        {
            continue;
        }
        const FString ItemName = TabId.ToString();
        CloseRequestedItems.Add(ItemName);
        LiveTab->RequestCloseTab();
        if (TabManager->FindExistingLiveTab(LiveTabId).IsValid())
        {
            RemainingLogTabs.Add(ItemName);
        }
        else
        {
            ClosedItems.Add(ItemName);
        }
    }

    FLevelEditorModule* LevelEditorModule =
        FModuleManager::Get().LoadModulePtr<FLevelEditorModule>(TEXT("LevelEditor"));
    if (!LevelEditorModule)
    {
        return EditorViewportFocusResult(
            CloseRequestedItems,
            ClosedItems,
            RemainingLogTabs,
            false,
            false,
            TEXT("level_editor_module_unavailable"),
            TEXT("The Level Editor module is unavailable")
        );
    }
    const TSharedPtr<ILevelEditor> LevelEditor = LevelEditorModule->GetFirstLevelEditor();
    const TSharedPtr<SDockTab> LevelEditorTab = LevelEditorModule->GetLevelEditorTab();
    if (!LevelEditor.IsValid() || !LevelEditorTab.IsValid())
    {
        return EditorViewportFocusResult(
            CloseRequestedItems,
            ClosedItems,
            RemainingLogTabs,
            false,
            false,
            TEXT("level_editor_unavailable"),
            TEXT("No active Level Editor is available")
        );
    }

    LevelEditorTab->ActivateInParent(ETabActivationCause::SetDirectly);
    const bool bLevelEditorActivated = LevelEditorTab->IsForeground();
    const auto ActiveViewport = LevelEditor->GetActiveViewportInterface();
    if (!ActiveViewport.IsValid())
    {
        return EditorViewportFocusResult(
            CloseRequestedItems,
            ClosedItems,
            RemainingLogTabs,
            bLevelEditorActivated,
            false,
            TEXT("active_viewport_unavailable"),
            TEXT("The Level Editor has no active viewport")
        );
    }

    const TSharedRef<SWidget> ViewportWidget = ActiveViewport->AsWidget();
    const TSharedPtr<SWindow> ViewportWindow = FSlateApplication::Get().FindWidgetWindow(ViewportWidget);
    if (ViewportWindow.IsValid())
    {
        ViewportWindow->BringToFront(true);
    }
    FSlateApplication::Get().SetAllUserFocus(ViewportWidget, EFocusCause::SetDirectly);
    const bool bFocusAccepted = FSlateApplication::Get().SetKeyboardFocus(
        ViewportWidget,
        EFocusCause::SetDirectly
    );
    const bool bViewportFocused = bFocusAccepted
        && (ViewportWidget->HasKeyboardFocus() || ViewportWidget->HasFocusedDescendants());
    return EditorViewportFocusResult(
        CloseRequestedItems,
        ClosedItems,
        RemainingLogTabs,
        bLevelEditorActivated,
        bViewportFocused
    );
}

FString UDccMcpAutomationLibrary::GetMaterialCustomizedUvConnection(
    UMaterial* Material,
    int32 CustomizedUvIndex
)
{
    if (!IsInGameThread())
    {
        return MaterialGraphError(TEXT("wrong_thread"), TEXT("Material graph inspection requires the game thread"));
    }
    if (!IsValid(Material))
    {
        return MaterialGraphError(TEXT("invalid_material"), TEXT("A valid Material asset is required"));
    }
    if (CustomizedUvIndex < 0 || CustomizedUvIndex >= 8 || !GetCustomizedUvInput(Material, CustomizedUvIndex))
    {
        return MaterialGraphError(
            TEXT("invalid_customized_uv_index"),
            TEXT("Customized UV index must be between 0 and 7")
        );
    }

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), true);
    AddCustomizedUvConnectionFields(Root, Material, CustomizedUvIndex);
    return SerializeJson(Root);
}

FString UDccMcpAutomationLibrary::ConfigureMaterialInstanceParameters(
    UMaterialInstanceConstant* Instance,
    const TMap<FString, float>& ScalarParameters,
    const TMap<FString, FLinearColor>& VectorParameters,
    const TMap<FString, UTexture*>& TextureParameters
)
{
    if (!IsInGameThread())
    {
        return MaterialGraphError(TEXT("wrong_thread"), TEXT("Material Instance mutation requires the game thread"));
    }
    if (!IsValid(Instance) || Instance->HasAnyFlags(RF_Transient | RF_ClassDefaultObject | RF_ArchetypeObject))
    {
        return MaterialGraphError(
            TEXT("invalid_material_instance"),
            TEXT("A persistent Material Instance Constant asset is required")
        );
    }
    if (ScalarParameters.Num() == 0 && VectorParameters.Num() == 0 && TextureParameters.Num() == 0)
    {
        return MaterialGraphError(
            TEXT("empty_parameter_set"),
            TEXT("At least one scalar, vector, or texture parameter is required")
        );
    }
    for (const TPair<FString, float>& Pair : ScalarParameters)
    {
        if (Pair.Key.TrimStartAndEnd().IsEmpty() || !FMath::IsFinite(Pair.Value))
        {
            return MaterialGraphError(
                TEXT("invalid_scalar_parameter"),
                TEXT("Scalar parameter names must be non-empty and values must be finite")
            );
        }
    }
    for (const TPair<FString, FLinearColor>& Pair : VectorParameters)
    {
        if (Pair.Key.TrimStartAndEnd().IsEmpty()
            || !FMath::IsFinite(Pair.Value.R)
            || !FMath::IsFinite(Pair.Value.G)
            || !FMath::IsFinite(Pair.Value.B)
            || !FMath::IsFinite(Pair.Value.A))
        {
            return MaterialGraphError(
                TEXT("invalid_vector_parameter"),
                TEXT("Vector parameter names must be non-empty and values must be finite")
            );
        }
    }
    for (const TPair<FString, UTexture*>& Pair : TextureParameters)
    {
        UPackage* TexturePackage = IsValid(Pair.Value) ? Pair.Value->GetOutermost() : nullptr;
        if (Pair.Key.TrimStartAndEnd().IsEmpty()
            || !IsValid(Pair.Value)
            || Pair.Value->HasAnyFlags(RF_Transient | RF_ClassDefaultObject | RF_ArchetypeObject)
            || !Pair.Value->HasAllFlags(RF_Public | RF_Standalone)
            || !TexturePackage
            || TexturePackage == GetTransientPackage()
            || TexturePackage->HasAnyFlags(RF_Transient))
        {
            return MaterialGraphError(
                TEXT("invalid_texture_parameter"),
                TEXT("Texture parameter names and persistent texture assets must be valid")
            );
        }
    }

    UPackage* Package = Instance->GetOutermost();
    const FString PackageName = Package ? Package->GetName() : FString();
    FString Filename;
    if (!Package || Package == GetTransientPackage() || Package->HasAnyFlags(RF_Transient)
        || !PackageName.StartsWith(TEXT("/Game/"), ESearchCase::CaseSensitive)
        || !FPackageName::TryConvertLongPackageNameToFilename(
            PackageName,
            Filename,
            FPackageName::GetAssetPackageExtension()
        ))
    {
        return MaterialGraphError(
            TEXT("invalid_material_instance_package"),
            TEXT("The Material Instance must be stored in a valid /Game asset package")
        );
    }
    if (Package->IsDirty())
    {
        return MaterialGraphError(
            TEXT("material_instance_package_dirty"),
            TEXT("Save or revert existing Material Instance changes before configuring parameters")
        );
    }

    const auto HasExpectedOverrides = [Instance, &ScalarParameters, &VectorParameters, &TextureParameters]()
    {
        for (const TPair<FString, float>& Pair : ScalarParameters)
        {
            const FName ExpectedName(*Pair.Key);
            const FScalarParameterValue* Match = Instance->ScalarParameterValues.FindByPredicate(
                [ExpectedName](const FScalarParameterValue& Value)
                {
                    return MaterialInstanceParameterMatches(Value, ExpectedName);
                }
            );
            if (!Match || !FMath::IsNearlyEqual(Match->ParameterValue, Pair.Value))
            {
                return false;
            }
        }
        for (const TPair<FString, FLinearColor>& Pair : VectorParameters)
        {
            const FName ExpectedName(*Pair.Key);
            const FVectorParameterValue* Match = Instance->VectorParameterValues.FindByPredicate(
                [ExpectedName](const FVectorParameterValue& Value)
                {
                    return MaterialInstanceParameterMatches(Value, ExpectedName);
                }
            );
            if (!Match || !Match->ParameterValue.Equals(Pair.Value))
            {
                return false;
            }
        }
        for (const TPair<FString, UTexture*>& Pair : TextureParameters)
        {
            const FName ExpectedName(*Pair.Key);
            const FTextureParameterValue* Match = Instance->TextureParameterValues.FindByPredicate(
                [ExpectedName](const FTextureParameterValue& Value)
                {
                    return MaterialInstanceParameterMatches(Value, ExpectedName);
                }
            );
            if (!Match || Match->ParameterValue != Pair.Value)
            {
                return false;
            }
        }
        return true;
    };
    if (HasExpectedOverrides())
    {
        TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
        Root->SetBoolField(TEXT("success"), true);
        Root->SetBoolField(TEXT("changed"), false);
        Root->SetBoolField(TEXT("saved"), true);
        Root->SetBoolField(TEXT("verified"), true);
        Root->SetNumberField(TEXT("scalar_parameter_count"), ScalarParameters.Num());
        Root->SetNumberField(TEXT("vector_parameter_count"), VectorParameters.Num());
        Root->SetNumberField(TEXT("texture_parameter_count"), TextureParameters.Num());
        Root->SetBoolField(TEXT("package_dirty"), false);
        return SerializeJson(Root);
    }

    const TArray<FScalarParameterValue> PreviousScalarParameters = Instance->ScalarParameterValues;
    const TArray<FVectorParameterValue> PreviousVectorParameters = Instance->VectorParameterValues;
    const TArray<FTextureParameterValue> PreviousTextureParameters = Instance->TextureParameterValues;
    FScopedTransaction Transaction(
        NSLOCTEXT("DccMcpUnreal", "ConfigureMaterialInstance", "DCC MCP Configure Material Instance")
    );
    Instance->Modify();
    Instance->PreEditChange(nullptr);
    for (const TPair<FString, float>& Pair : ScalarParameters)
    {
        SetMaterialInstanceScalarOverride(Instance, FName(*Pair.Key), Pair.Value);
    }
    for (const TPair<FString, FLinearColor>& Pair : VectorParameters)
    {
        SetMaterialInstanceVectorOverride(Instance, FName(*Pair.Key), Pair.Value);
    }
    for (const TPair<FString, UTexture*>& Pair : TextureParameters)
    {
        SetMaterialInstanceTextureOverride(Instance, FName(*Pair.Key), Pair.Value);
    }
    Instance->PostEditChange();
#if ENGINE_MAJOR_VERSION >= 5
    Instance->EnsureIsComplete();
#endif

    const auto RestorePreviousOverrides = [
        Instance,
        Package,
        PreviousScalarParameters,
        PreviousVectorParameters,
        PreviousTextureParameters
    ]()
    {
        Instance->PreEditChange(nullptr);
        Instance->ScalarParameterValues = PreviousScalarParameters;
        Instance->VectorParameterValues = PreviousVectorParameters;
        Instance->TextureParameterValues = PreviousTextureParameters;
        Instance->PostEditChange();
        Package->SetDirtyFlag(false);
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
        const auto ScalarArraysEqual = [](
            const TArray<FScalarParameterValue>& Left,
            const TArray<FScalarParameterValue>& Right
        )
        {
            if (Left.Num() != Right.Num())
            {
                return false;
            }
            for (int32 Index = 0; Index < Left.Num(); ++Index)
            {
                if (Left[Index].ParameterName != Right[Index].ParameterName
                    || !FMath::IsNearlyEqual(Left[Index].ParameterValue, Right[Index].ParameterValue)
                    || Left[Index].ExpressionGUID != Right[Index].ExpressionGUID)
                {
                    return false;
                }
            }
            return true;
        };
        const auto VectorArraysEqual = [](
            const TArray<FVectorParameterValue>& Left,
            const TArray<FVectorParameterValue>& Right
        )
        {
            if (Left.Num() != Right.Num())
            {
                return false;
            }
            for (int32 Index = 0; Index < Left.Num(); ++Index)
            {
                if (Left[Index].ParameterName != Right[Index].ParameterName
                    || Left[Index].ParameterValue != Right[Index].ParameterValue
                    || Left[Index].ExpressionGUID != Right[Index].ExpressionGUID)
                {
                    return false;
                }
            }
            return true;
        };
        const auto TextureArraysEqual = [](
            const TArray<FTextureParameterValue>& Left,
            const TArray<FTextureParameterValue>& Right
        )
        {
            if (Left.Num() != Right.Num())
            {
                return false;
            }
            for (int32 Index = 0; Index < Left.Num(); ++Index)
            {
                if (Left[Index].ParameterName != Right[Index].ParameterName
                    || Left[Index].ParameterValue != Right[Index].ParameterValue
                    || Left[Index].ExpressionGUID != Right[Index].ExpressionGUID)
                {
                    return false;
                }
            }
            return true;
        };
        return ScalarArraysEqual(Instance->ScalarParameterValues, PreviousScalarParameters)
            && VectorArraysEqual(Instance->VectorParameterValues, PreviousVectorParameters)
            && TextureArraysEqual(Instance->TextureParameterValues, PreviousTextureParameters)
            && !Package->IsDirty();
#else
        return Instance->ScalarParameterValues == PreviousScalarParameters
            && Instance->VectorParameterValues == PreviousVectorParameters
            && Instance->TextureParameterValues == PreviousTextureParameters
            && !Package->IsDirty();
#endif
    };

    if (!HasExpectedOverrides())
    {
        const bool bRolledBack = RestorePreviousOverrides();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("postcondition_not_met"),
            TEXT("Material Instance overrides did not match the requested values"),
            bRolledBack
        );
    }
    if (!SaveAssetPackage(Instance, Filename))
    {
        const bool bRolledBack = RestorePreviousOverrides();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("material_instance_save_failed"),
            TEXT("Unreal failed to save the Material Instance package; in-memory overrides were rolled back"),
            bRolledBack
        );
    }
    if (!HasExpectedOverrides() || Package->IsDirty())
    {
        const bool bRestoredInMemory = RestorePreviousOverrides();
        const bool bRestoredOnDisk = bRestoredInMemory
            && SaveAssetPackage(Instance, Filename)
            && !Package->IsDirty();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("post_save_verification_failed"),
            TEXT("Saved Material Instance state failed verification and rollback was attempted"),
            bRestoredOnDisk
        );
    }

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), true);
    Root->SetBoolField(TEXT("changed"), true);
    Root->SetBoolField(TEXT("saved"), true);
    Root->SetBoolField(TEXT("verified"), true);
    Root->SetNumberField(TEXT("scalar_parameter_count"), ScalarParameters.Num());
    Root->SetNumberField(TEXT("vector_parameter_count"), VectorParameters.Num());
    Root->SetNumberField(TEXT("texture_parameter_count"), TextureParameters.Num());
    Root->SetBoolField(TEXT("package_dirty"), Package->IsDirty());
    return SerializeJson(Root);
}

FString UDccMcpAutomationLibrary::ConnectMaterialExpressionToCustomizedUv(
    UMaterial* Material,
    UMaterialExpression* SourceExpression,
    int32 SourceOutputIndex,
    const FString& SourceOutputName,
    int32 CustomizedUvIndex,
    bool bReplaceExisting
)
{
    if (!IsInGameThread())
    {
        return MaterialGraphError(TEXT("wrong_thread"), TEXT("Material graph mutation requires the game thread"));
    }
    if (!IsValid(Material) || Material->HasAnyFlags(RF_Transient | RF_ClassDefaultObject | RF_ArchetypeObject))
    {
        return MaterialGraphError(TEXT("invalid_material"), TEXT("A persistent Material asset is required"));
    }
    if (!IsValid(SourceExpression) || !MaterialOwnsExpression(Material, SourceExpression))
    {
        return MaterialGraphError(
            TEXT("expression_ownership_mismatch"),
            TEXT("The source expression must belong to the target Material")
        );
    }
    if (CustomizedUvIndex < 0 || CustomizedUvIndex >= 8)
    {
        return MaterialGraphError(
            TEXT("invalid_customized_uv_index"),
            TEXT("Customized UV index must be between 0 and 7")
        );
    }

    if (SourceOutputIndex < -1)
    {
        return MaterialGraphError(
            TEXT("invalid_output_selector"),
            TEXT("Source output index must be -1 when selecting by exact name")
        );
    }
    const bool bHasOutputIndex = SourceOutputIndex >= 0;
    const bool bHasOutputName = !SourceOutputName.IsEmpty() && !SourceOutputName.TrimStartAndEnd().IsEmpty();
    if (bHasOutputIndex == bHasOutputName)
    {
        return MaterialGraphError(
            TEXT("invalid_output_selector"),
            TEXT("Select exactly one source output by index or exact name")
        );
    }

    TArray<FExpressionOutput>& Outputs = SourceExpression->GetOutputs();
    int32 ResolvedOutputIndex = INDEX_NONE;
    if (bHasOutputIndex)
    {
        if (!Outputs.IsValidIndex(SourceOutputIndex))
        {
            return MaterialGraphError(
                TEXT("source_output_not_found"),
                FString::Printf(TEXT("Source output index %d is out of range"), SourceOutputIndex)
            );
        }
        ResolvedOutputIndex = SourceOutputIndex;
    }
    else
    {
        int32 MatchCount = 0;
        for (int32 Index = 0; Index < Outputs.Num(); ++Index)
        {
            if (MaterialOutputName(Outputs[Index]).Equals(SourceOutputName, ESearchCase::CaseSensitive))
            {
                ResolvedOutputIndex = Index;
                ++MatchCount;
            }
        }
        if (MatchCount != 1)
        {
            return MaterialGraphError(
                TEXT("source_output_not_found"),
                FString::Printf(
                    TEXT("Source output name '%s' matched %d outputs; exactly one is required"),
                    *SourceOutputName,
                    MatchCount
                )
            );
        }
    }

    UPackage* Package = Material->GetOutermost();
    const FString PackageName = Package ? Package->GetName() : FString();
    FString Filename;
    if (!Package || Package == GetTransientPackage() || Package->HasAnyFlags(RF_Transient)
        || !PackageName.StartsWith(TEXT("/Game/"), ESearchCase::CaseSensitive)
        || !FPackageName::TryConvertLongPackageNameToFilename(
            PackageName,
            Filename,
            FPackageName::GetAssetPackageExtension()
        ))
    {
        return MaterialGraphError(
            TEXT("invalid_material_package"),
            TEXT("The Material must be stored in a valid /Game asset package")
        );
    }
    if (Package->IsDirty())
    {
        return MaterialGraphError(
            TEXT("material_package_dirty"),
            TEXT("Save or revert existing Material changes before connecting a Customized UV input")
        );
    }

    FVector2MaterialInput* TargetInput = GetCustomizedUvInput(Material, CustomizedUvIndex);
    if (!TargetInput)
    {
        return MaterialGraphError(
            TEXT("editor_only_data_unavailable"),
            TEXT("Material editor-only graph data is unavailable")
        );
    }
    if (TargetInput->Expression == SourceExpression
        && TargetInput->OutputIndex == ResolvedOutputIndex
        && Material->NumCustomizedUVs >= CustomizedUvIndex + 1)
    {
        TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
        Root->SetBoolField(TEXT("success"), true);
        Root->SetBoolField(TEXT("changed"), false);
        Root->SetBoolField(TEXT("saved"), true);
        Root->SetBoolField(TEXT("verified"), true);
        AddCustomizedUvConnectionFields(Root, Material, CustomizedUvIndex);
        return SerializeJson(Root);
    }
    if (TargetInput->Expression && !bReplaceExisting)
    {
        return MaterialGraphError(
            TEXT("customized_uv_occupied"),
            TEXT("Customized UV input already has a different connection; set replace_existing=true to replace it")
        );
    }

    const FVector2MaterialInput PreviousInput = *TargetInput;
    const int32 PreviousNumCustomizedUvs = Material->NumCustomizedUVs;
    FScopedTransaction Transaction(
        NSLOCTEXT("DccMcpUnreal", "ConnectCustomizedUv", "DCC MCP Connect Customized UV")
    );
    Material->Modify();
    Material->PreEditChange(nullptr);
#if ENGINE_MAJOR_VERSION >= 5
    UMaterialEditorOnlyData* EditorOnlyData = Material->GetEditorOnlyData();
    if (!EditorOnlyData)
    {
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("editor_only_data_unavailable"),
            TEXT("Material editor-only graph data is unavailable")
        );
    }
    EditorOnlyData->CustomizedUVs[CustomizedUvIndex].Connect(ResolvedOutputIndex, SourceExpression);
#else
    Material->CustomizedUVs[CustomizedUvIndex].Connect(ResolvedOutputIndex, SourceExpression);
#endif
    Material->NumCustomizedUVs = FMath::Max(Material->NumCustomizedUVs, CustomizedUvIndex + 1);
    Material->PostEditChange();
#if ENGINE_MAJOR_VERSION >= 5
    Material->EnsureIsComplete();
#endif

    const auto HasExpectedConnection = [Material, SourceExpression, ResolvedOutputIndex, CustomizedUvIndex]()
    {
        const FVector2MaterialInput* Input = GetCustomizedUvInput(Material, CustomizedUvIndex);
        return Input && Input->Expression == SourceExpression && Input->OutputIndex == ResolvedOutputIndex
            && Material->NumCustomizedUVs >= CustomizedUvIndex + 1;
    };
    const auto RestorePreviousConnection = [
        Material,
        Package,
        CustomizedUvIndex,
        PreviousInput,
        PreviousNumCustomizedUvs
    ]()
    {
        FVector2MaterialInput* Input = GetCustomizedUvInput(Material, CustomizedUvIndex);
        if (!Input)
        {
            return false;
        }
        Material->PreEditChange(nullptr);
        *Input = PreviousInput;
        Material->NumCustomizedUVs = PreviousNumCustomizedUvs;
        Material->PostEditChange();
        Package->SetDirtyFlag(false);
        return Input->Expression == PreviousInput.Expression
            && Input->OutputIndex == PreviousInput.OutputIndex
            && Material->NumCustomizedUVs == PreviousNumCustomizedUvs
            && !Package->IsDirty();
    };

    if (!HasExpectedConnection())
    {
        const bool bRolledBack = RestorePreviousConnection();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("postcondition_not_met"),
            TEXT("Customized UV connection did not match the requested graph state"),
            bRolledBack
        );
    }
    if (!SaveMaterialPackage(Material, Filename))
    {
        const bool bRolledBack = RestorePreviousConnection();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("material_save_failed"),
            TEXT("Unreal failed to save the Material package; the in-memory connection was rolled back"),
            bRolledBack
        );
    }
    if (!HasExpectedConnection() || Package->IsDirty())
    {
        const bool bRestoredInMemory = RestorePreviousConnection();
        const bool bRestoredOnDisk = bRestoredInMemory && SaveMaterialPackage(Material, Filename) && !Package->IsDirty();
        Transaction.Cancel();
        return MaterialGraphError(
            TEXT("post_save_verification_failed"),
            TEXT("Saved Material state failed verification and rollback was attempted"),
            bRestoredOnDisk
        );
    }

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetBoolField(TEXT("success"), true);
    Root->SetBoolField(TEXT("changed"), true);
    Root->SetBoolField(TEXT("saved"), true);
    Root->SetBoolField(TEXT("verified"), true);
    AddCustomizedUvConnectionFields(Root, Material, CustomizedUvIndex);
    return SerializeJson(Root);
}

FString UDccMcpAutomationLibrary::CreateGeometryCollectionFromStaticMesh(
    const FString& StaticMeshPath,
    const FString& DestinationPath,
    const FString& AssetName,
    float DamageThreshold
)
{
#if ENGINE_MAJOR_VERSION < 5
    UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos requires Unreal Engine 5 or newer"));
    return FString();
#else
    if (!FPackageName::IsValidLongPackageName(DestinationPath) || !DestinationPath.StartsWith(TEXT("/Game")))
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: destination_path must be a valid /Game package path"));
        return FString();
    }
    if (AssetName.IsEmpty() || AssetName != FPackageName::GetShortName(AssetName))
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: asset_name must be a simple Unreal asset name"));
        return FString();
    }
    if (DamageThreshold <= 0.0f)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: damage_threshold must be greater than zero"));
        return FString();
    }

    UStaticMesh* StaticMesh = LoadObject<UStaticMesh>(nullptr, *StaticMeshPath);
    if (!StaticMesh)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: StaticMesh not found: %s"), *StaticMeshPath);
        return FString();
    }

    const FString PackagePath = DestinationPath / AssetName;
    const FString AssetPath = PackagePath + TEXT(".") + AssetName;
    if (FindObject<UGeometryCollection>(nullptr, *AssetPath) || FPackageName::DoesPackageExist(PackagePath))
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: Geometry Collection already exists: %s"), *AssetPath);
        return FString();
    }

    UPackage* Package = CreatePackage(*PackagePath);
    UGeometryCollection* GeometryCollection = NewObject<UGeometryCollection>(
        Package,
        UGeometryCollection::StaticClass(),
        FName(*AssetName),
        RF_Public | RF_Standalone | RF_Transactional
    );
    if (!GeometryCollection)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: Unreal failed to create the Geometry Collection asset"));
        return FString();
    }

    TArray<UMaterialInterface*> Materials;
    for (const FStaticMaterial& StaticMaterial : StaticMesh->GetStaticMaterials())
    {
        Materials.Add(StaticMaterial.MaterialInterface);
    }
    if (!FGeometryCollectionEngineConversion::AppendStaticMesh(
            StaticMesh,
            Materials,
            FTransform::Identity,
            GeometryCollection,
            true,
            true,
            true
        ))
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: Failed to convert StaticMesh: %s"), *StaticMeshPath);
        return FString();
    }

    TSharedPtr<FGeometryCollection, ESPMode::ThreadSafe> CollectionData = GeometryCollection->GetGeometryCollection();
    if (FGeometryCollectionClusteringUtility::ContainsMultipleRootBones(CollectionData.Get()))
    {
        FGeometryCollectionClusteringUtility::ClusterAllBonesUnderNewRoot(CollectionData.Get());
    }
    GeometryCollection->EnableClustering = true;
    GeometryCollection->DamageThreshold = {DamageThreshold};
    GeometryCollection->InitializeMaterials();
    GeometryCollectionAlgo::PrepareForSimulation(GeometryCollection->GetGeometryCollection().Get());
    GeometryCollection->PostEditChange();
    GeometryCollection->MarkPackageDirty();
    FAssetRegistryModule::AssetCreated(GeometryCollection);
    return AssetPath;
#endif
}

FString UDccMcpAutomationLibrary::SpawnGeometryCollectionActor(
    const FString& GeometryCollectionPath,
    float LocationX,
    float LocationY,
    float LocationZ,
    float DamageThreshold,
    const FString& Label
)
{
#if ENGINE_MAJOR_VERSION < 5
    UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos requires Unreal Engine 5 or newer"));
    return FString();
#else
    if (DamageThreshold <= 0.0f)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: damage_threshold must be greater than zero"));
        return FString();
    }

    UGeometryCollection* GeometryCollection = LoadObject<UGeometryCollection>(nullptr, *GeometryCollectionPath);
    if (!GeometryCollection)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: Geometry Collection not found: %s"), *GeometryCollectionPath);
        return FString();
    }
    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!World)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: No editor world is available"));
        return FString();
    }

    AGeometryCollectionActor* Actor = World->SpawnActor<AGeometryCollectionActor>(
        AGeometryCollectionActor::StaticClass(),
        FVector(LocationX, LocationY, LocationZ),
        FRotator::ZeroRotator
    );
    UGeometryCollectionComponent* Component = Actor ? Actor->GetGeometryCollectionComponent() : nullptr;
    if (!Component)
    {
        UE_LOG(LogTemp, Error, TEXT("DCC MCP Chaos: Unreal failed to spawn a Geometry Collection actor"));
        return FString();
    }
    Component->SetRestCollection(GeometryCollection);
    Component->SetDamageThreshold({DamageThreshold});
    if (!Label.IsEmpty())
    {
        Actor->SetActorLabel(Label);
    }
    Actor->Modify();
    return Actor->GetName();
#endif
}
