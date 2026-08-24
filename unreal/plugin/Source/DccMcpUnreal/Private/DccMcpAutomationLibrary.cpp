#include "DccMcpAutomationLibrary.h"

#include "Runtime/Launch/Resources/Version.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "AssetRegistry/AssetRegistryModule.h"
#else
#include "AssetRegistryModule.h"
#endif
#include "Editor.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/PlayerController.h"
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
#include "GameFramework/PlayerInput.h"
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
#include "Materials/MaterialInterface.h"
#include "Misc/AutomationTest.h"
#include "Misc/PackageName.h"
#include "Modules/ModuleManager.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/Package.h"
#include "UObject/UObjectGlobals.h"

namespace
{
constexpr TCHAR FabModuleName[] = TEXT("Fab");
constexpr TCHAR FabApiClassPath[] = TEXT("/Script/Fab.FabBrowserApi");
constexpr TCHAR FabListingPrefix[] = TEXT("https://fab.com/plugins/ue5/listings/");

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

APlayerController* GetPiePlayerController()
{
    UWorld* PlayWorld = GEditor ? GEditor->PlayWorld : nullptr;
    return PlayWorld ? PlayWorld->GetFirstPlayerController() : nullptr;
}

bool InjectPlayerInput(APlayerController* PlayerController, const FKey& Key, EInputEvent Event, float Value)
{
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 1)
    if (Event == IE_Axis)
    {
        constexpr float AxisDeltaTime = 1.0f / 60.0f;
        return PlayerController->InputKey(
            FInputKeyParams(Key, static_cast<double>(Value), AxisDeltaTime, 1, false)
        );
    }
    return PlayerController->InputKey(FInputKeyParams(Key, Event, static_cast<double>(Value), false));
#else
    return PlayerController->InputKey(Key, Event, Value, false);
#endif
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

bool UDccMcpAutomationLibrary::InjectPieKey(const FString& KeyName, bool bPressed)
{
    APlayerController* PlayerController = GetPiePlayerController();
    const FKey Key = FKey(FName(*KeyName));
    if (!PlayerController || !Key.IsValid())
    {
        return false;
    }
    return InjectPlayerInput(PlayerController, Key, bPressed ? IE_Pressed : IE_Released, bPressed ? 1.0f : 0.0f);
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
