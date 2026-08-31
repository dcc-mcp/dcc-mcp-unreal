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
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerInput.h"
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
#include "GenericPlatform/GenericPlatformInputDeviceMapper.h"
#endif
#include "InputCoreTypes.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "GeometryCollection/GeometryCollectionActor.h"
#include "GeometryCollection/GeometryCollectionAlgo.h"
#include "GeometryCollection/GeometryCollectionClusteringUtility.h"
#include "GeometryCollection/GeometryCollectionComponent.h"
#include "GeometryCollection/GeometryCollectionEngineConversion.h"
#include "GeometryCollection/GeometryCollectionObject.h"
#endif
#include "Interfaces/IPluginManager.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Materials/MaterialInterface.h"
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
#include "Widgets/SWindow.h"

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

bool SaveMaterialPackage(UMaterial* Material, const FString& Filename)
{
    UPackage* Package = Material ? Material->GetOutermost() : nullptr;
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
    return UPackage::SavePackage(Package, Material, *Filename, SaveArgs);
#else
    return UPackage::SavePackage(
        Package,
        Material,
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
