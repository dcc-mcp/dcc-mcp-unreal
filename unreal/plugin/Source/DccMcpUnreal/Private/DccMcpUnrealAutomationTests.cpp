#include "DccMcpAutomationLibrary.h"

#include "Dom/JsonObject.h"
#include "Engine/Texture2D.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionConstant.h"
#include "Materials/MaterialInstanceConstant.h"
#include "Misc/AutomationTest.h"
#include "Misc/Guid.h"
#include "Misc/PackageName.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/Package.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "UObject/SavePackage.h"
#endif
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 8)
#include "NiagaraSystem.h"
#endif

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpUnrealNativeSmokeTest,
    "DccMcp.Smoke.NativeBridge",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpUnrealNativeSmokeTest::RunTest(const FString& Parameters)
{
    if (!IPluginManager::Get().FindPlugin(TEXT("DccMcpUnreal")).IsValid())
    {
        AddError(TEXT("DccMcpUnreal plugin is not registered with IPluginManager."));
        return false;
    }

    const TArray<FString> EnabledPlugins = UDccMcpAutomationLibrary::GetEnabledPluginNames();
    if (!EnabledPlugins.Contains(TEXT("DccMcpUnreal")))
    {
        AddError(TEXT("Enabled plugin preflight omitted DccMcpUnreal."));
        return false;
    }

    TSharedPtr<FJsonObject> Result;
    const TSharedRef<TJsonReader<>> Reader =
        TJsonReaderFactory<>::Create(UDccMcpAutomationLibrary::ListAutomationTestsJson(TEXT("DccMcp")));
    if (!FJsonSerializer::Deserialize(Reader, Result) || !Result.IsValid())
    {
        AddError(TEXT("Native automation bridge returned invalid JSON."));
        return false;
    }

    double Count = 0.0;
    if (!Result->TryGetNumberField(TEXT("count"), Count) || Count < 1.0)
    {
        AddError(TEXT("Native automation bridge did not discover DCC MCP tests."));
        return false;
    }

    TSharedPtr<FJsonObject> FabStatus;
    const TSharedRef<TJsonReader<>> FabReader =
        TJsonReaderFactory<>::Create(UDccMcpAutomationLibrary::GetFabSessionStatusJson());
    bool bFabAvailable = false;
    bool bFabAuthenticated = false;
    if (!FJsonSerializer::Deserialize(FabReader, FabStatus) || !FabStatus.IsValid()
        || !FabStatus->TryGetBoolField(TEXT("plugin_available"), bFabAvailable)
        || !FabStatus->TryGetBoolField(TEXT("authenticated"), bFabAuthenticated))
    {
        AddError(TEXT("Fab session bridge returned invalid or unsafe status JSON."));
        return false;
    }
    return true;
}

#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 8)
IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpNiagaraSemanticAuthoringTest,
    "DccMcp.Smoke.NiagaraSemanticAuthoring",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpNiagaraSemanticAuthoringTest::RunTest(const FString& Parameters)
{
    const FString AssetName = FString::Printf(
        TEXT("NS_DccMcpChainExplosion_%s"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)
    );
    const FString PackagePath = TEXT("/Game/DccMcpAutomation");
    const FString SystemPath = PackagePath / AssetName;

    const auto NumberInput = [](const FString& Type, double Value)
    {
        TSharedRef<FJsonObject> Input = MakeShared<FJsonObject>();
        Input->SetStringField(TEXT("type"), Type);
        Input->SetNumberField(TEXT("value"), Value);
        return MakeShared<FJsonValueObject>(Input);
    };
    const auto VectorInput = [](double X, double Y, double Z)
    {
        TSharedRef<FJsonObject> Input = MakeShared<FJsonObject>();
        Input->SetStringField(TEXT("type"), TEXT("vector3"));
        TArray<TSharedPtr<FJsonValue>> Values;
        Values.Add(MakeShared<FJsonValueNumber>(X));
        Values.Add(MakeShared<FJsonValueNumber>(Y));
        Values.Add(MakeShared<FJsonValueNumber>(Z));
        Input->SetArrayField(TEXT("value"), Values);
        return MakeShared<FJsonValueObject>(Input);
    };
    const auto Module = [](
        const FString& Name,
        const FString& Script,
        const FString& AssetPath,
        const TSharedRef<FJsonObject>& Inputs
    )
    {
        TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetStringField(TEXT("name"), Name);
        Result->SetStringField(TEXT("script"), Script);
        Result->SetStringField(TEXT("asset_path"), AssetPath);
        Result->SetObjectField(TEXT("inputs"), Inputs);
        return MakeShared<FJsonValueObject>(Result);
    };

    TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
    Root->SetStringField(TEXT("asset_name"), AssetName);
    Root->SetStringField(TEXT("asset_path"), PackagePath);
    TArray<TSharedPtr<FJsonValue>> Emitters;
    const TCHAR* Layers[] = {TEXT("core"), TEXT("plume"), TEXT("sparks")};
    for (int32 Stage = 1; Stage <= 5; ++Stage)
    {
        for (const TCHAR* Layer : Layers)
        {
            TSharedRef<FJsonObject> Emitter = MakeShared<FJsonObject>();
            Emitter->SetStringField(TEXT("name"), FString::Printf(TEXT("Stage%d_%s"), Stage, Layer));
            TArray<TSharedPtr<FJsonValue>> Modules;

            TSharedRef<FJsonObject> BurstInputs = MakeShared<FJsonObject>();
            BurstInputs->SetField(TEXT("Spawn Count"), NumberInput(TEXT("int"), Stage * 10));
            Modules.Add(Module(
                TEXT("SpawnBurst"),
                TEXT("emitter_update"),
                TEXT("/Niagara/Modules/Emitter/SpawnBurst_Instantaneous.SpawnBurst_Instantaneous"),
                BurstInputs
            ));

            TSharedRef<FJsonObject> ShapeInputs = MakeShared<FJsonObject>();
            ShapeInputs->SetField(TEXT("Sphere Radius"), NumberInput(TEXT("float"), 50.0 * Stage));
            Modules.Add(Module(
                TEXT("ShapeLocation"),
                TEXT("particle_spawn"),
                TEXT("/Niagara/Modules/Spawn/Location/V2/ShapeLocation.ShapeLocation"),
                ShapeInputs
            ));

            TSharedRef<FJsonObject> VelocityInputs = MakeShared<FJsonObject>();
            VelocityInputs->SetField(TEXT("Velocity"), VectorInput(0.0, 0.0, 250.0 * Stage));
            Modules.Add(Module(
                TEXT("AddVelocity"),
                TEXT("particle_spawn"),
                TEXT("/Niagara/Modules/Spawn/Velocity/AddVelocity.AddVelocity"),
                VelocityInputs
            ));

            TSharedRef<FJsonObject> GravityInputs = MakeShared<FJsonObject>();
            GravityInputs->SetField(TEXT("Gravity"), VectorInput(0.0, 0.0, -980.0));
            Modules.Add(Module(
                TEXT("GravityForce"),
                TEXT("particle_update"),
                TEXT("/Niagara/Modules/Update/Forces/GravityForce.GravityForce"),
                GravityInputs
            ));
            Emitter->SetArrayField(TEXT("modules"), Modules);

            TSharedRef<FJsonObject> Renderer = MakeShared<FJsonObject>();
            Renderer->SetStringField(TEXT("name"), TEXT("SpriteRenderer"));
            Renderer->SetStringField(
                TEXT("class_path"),
                TEXT("/Script/Niagara.NiagaraSpriteRendererProperties")
            );
            TArray<TSharedPtr<FJsonValue>> Renderers;
            Renderers.Add(MakeShared<FJsonValueObject>(Renderer));
            Emitter->SetArrayField(TEXT("renderers"), Renderers);
            Emitters.Add(MakeShared<FJsonValueObject>(Emitter));
        }
    }
    Root->SetArrayField(TEXT("emitters"), Emitters);

    FString SpecificationJson;
    const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&SpecificationJson);
    FJsonSerializer::Serialize(Root, Writer);
    const FString Payload = UDccMcpAutomationLibrary::AuthorNiagaraSystemJson(SpecificationJson);

    TSharedPtr<FJsonObject> Result;
    const TSharedRef<TJsonReader<>> ResultReader = TJsonReaderFactory<>::Create(Payload);
    bool bSuccess = false;
    bool bSaved = false;
    bool bVerified = false;
    double EmitterCount = 0.0;
    double ModuleCount = 0.0;
    double RendererCount = 0.0;
    const bool bValid = FJsonSerializer::Deserialize(ResultReader, Result) && Result.IsValid()
        && Result->TryGetBoolField(TEXT("success"), bSuccess)
        && Result->TryGetBoolField(TEXT("saved"), bSaved)
        && Result->TryGetBoolField(TEXT("verified"), bVerified)
        && Result->TryGetNumberField(TEXT("emitter_count"), EmitterCount)
        && Result->TryGetNumberField(TEXT("module_count"), ModuleCount)
        && Result->TryGetNumberField(TEXT("renderer_count"), RendererCount);
    TestTrue(TEXT("Niagara authoring returned valid JSON"), bValid);
    TestTrue(TEXT("Niagara authoring succeeded"), bSuccess);
    TestTrue(TEXT("Niagara authoring saved the system"), bSaved);
    TestTrue(TEXT("Niagara authoring verified the saved topology"), bVerified);
    TestEqual(TEXT("Five stages with core, plume, and sparks emitters"), static_cast<int32>(EmitterCount), 15);
    TestTrue(TEXT("Every emitter contains the four requested modules"), ModuleCount >= 60.0);
    TestTrue(TEXT("Every emitter contains a SpriteRenderer"), RendererCount >= 15.0);

    UNiagaraSystem* System = LoadObject<UNiagaraSystem>(nullptr, *(SystemPath + TEXT(".") + AssetName));
    bool bCleaned = System != nullptr;
    if (System)
    {
        System->WaitForCompilationComplete(false, false);
        System->GetOutermost()->SetDirtyFlag(false);
    }
    const FString Filename = FPackageName::LongPackageNameToFilename(
        SystemPath,
        FPackageName::GetAssetPackageExtension()
    );
    bCleaned &= IFileManager::Get().Delete(*Filename, false, true, true);
    TestTrue(TEXT("Niagara automation asset was cleaned up"), bCleaned);
    return bValid && bSuccess && bSaved && bVerified
        && static_cast<int32>(EmitterCount) == 15
        && ModuleCount >= 60.0 && RendererCount >= 15.0 && bCleaned;
}
#endif

namespace
{
bool SaveAutomationAsset(UObject* Asset, const FString& Filename)
{
    UPackage* Package = Asset ? Asset->GetOutermost() : nullptr;
    if (!Package)
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
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpCustomizedUvBridgeTest,
    "DccMcp.Smoke.MaterialCustomizedUvBridge",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpCustomizedUvBridgeTest::RunTest(const FString& Parameters)
{
    const FString AssetName = FString::Printf(
        TEXT("M_DccMcpCustomizedUv_%s"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)
    );
    const FString PackageName = TEXT("/Game/DccMcpAutomation/") + AssetName;
    const FString Filename = FPackageName::LongPackageNameToFilename(
        PackageName,
        FPackageName::GetAssetPackageExtension()
    );
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26
    UPackage* Package = CreatePackage(nullptr, *PackageName);
#else
    UPackage* Package = CreatePackage(*PackageName);
#endif
    UMaterial* Material = NewObject<UMaterial>(
        Package,
        FName(*AssetName),
        RF_Public | RF_Standalone | RF_Transactional
    );
    UMaterialExpressionConstant* Expression = Material
        ? NewObject<UMaterialExpressionConstant>(Material, NAME_None, RF_Transactional)
        : nullptr;
    if (!Material || !Expression)
    {
        AddError(TEXT("Failed to create the automation Material graph."));
        return false;
    }

    Expression->Material = Material;
    Expression->MaterialExpressionGuid = FGuid::NewGuid();
    Expression->Outputs.SetNum(22);
    Expression->Outputs[19].OutputName = TEXT("Position");
    Expression->Outputs[20].OutputName = TEXT("Normal");
    Expression->Outputs[21].OutputName = TEXT("Velocity");
#if ENGINE_MAJOR_VERSION >= 5
    UMaterialEditorOnlyData* EditorOnlyData = Material->GetEditorOnlyData();
    if (!EditorOnlyData)
    {
        AddError(TEXT("Material editor-only data was unavailable."));
        return false;
    }
    EditorOnlyData->ExpressionCollection.Expressions.Add(Expression);
#else
    Material->Expressions.Add(Expression);
#endif
    Material->MarkPackageDirty();
    if (!SaveAutomationAsset(Material, Filename) || Package->IsDirty())
    {
        AddError(TEXT("Failed to save the baseline automation Material."));
        IFileManager::Get().Delete(*Filename, false, true, true);
        return false;
    }

    const auto VerifyResult = [this](const FString& Payload, int32 ExpectedUv, int32 ExpectedOutput)
    {
        TSharedPtr<FJsonObject> Result;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Payload);
        bool bSuccess = false;
        bool bVerified = false;
        bool bPackageDirty = true;
        double ActualUv = -1.0;
        double ActualOutput = -1.0;
        const bool bValid = FJsonSerializer::Deserialize(Reader, Result) && Result.IsValid()
            && Result->TryGetBoolField(TEXT("success"), bSuccess)
            && Result->TryGetNumberField(TEXT("customized_uv_index"), ActualUv)
            && Result->TryGetNumberField(TEXT("source_output_index"), ActualOutput)
            && Result->TryGetBoolField(TEXT("package_dirty"), bPackageDirty);
        if (Result.IsValid() && Result->HasField(TEXT("verified")))
        {
            Result->TryGetBoolField(TEXT("verified"), bVerified);
        }
        else
        {
            bVerified = bSuccess;
        }
        TestTrue(TEXT("Native material bridge returned valid JSON"), bValid);
        TestTrue(TEXT("Native material bridge reported success"), bSuccess);
        TestTrue(TEXT("Native material bridge verified the connection"), bVerified);
        TestEqual(TEXT("Customized UV index matches"), static_cast<int32>(ActualUv), ExpectedUv);
        TestEqual(TEXT("Source output index matches"), static_cast<int32>(ActualOutput), ExpectedOutput);
        TestFalse(TEXT("Saved Material package is clean"), bPackageDirty);
        return bValid && bSuccess && bVerified && !bPackageDirty
            && static_cast<int32>(ActualUv) == ExpectedUv
            && static_cast<int32>(ActualOutput) == ExpectedOutput;
    };

    bool bPassed = true;
    bPassed &= VerifyResult(
        UDccMcpAutomationLibrary::ConnectMaterialExpressionToCustomizedUv(
            Material,
            Expression,
            19,
            FString(),
            1,
            false
        ),
        1,
        19
    );
    bPassed &= VerifyResult(
        UDccMcpAutomationLibrary::ConnectMaterialExpressionToCustomizedUv(
            Material,
            Expression,
            -1,
            TEXT("Normal"),
            2,
            false
        ),
        2,
        20
    );
    bPassed &= VerifyResult(
        UDccMcpAutomationLibrary::ConnectMaterialExpressionToCustomizedUv(
            Material,
            Expression,
            21,
            FString(),
            3,
            false
        ),
        3,
        21
    );
    bPassed &= VerifyResult(
        UDccMcpAutomationLibrary::GetMaterialCustomizedUvConnection(Material, 2),
        2,
        20
    );

    Package->SetDirtyFlag(false);
    if (!IFileManager::Get().Delete(*Filename, false, true, true))
    {
        AddError(TEXT("Failed to remove the automation Material package."));
        bPassed = false;
    }
    return bPassed;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpMaterialInstanceParameterIdentityTest,
    "DccMcp.Smoke.MaterialInstanceParameterIdentity",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpMaterialInstanceParameterIdentityTest::RunTest(const FString& Parameters)
{
    const FString AssetName = FString::Printf(
        TEXT("MI_DccMcpParameterIdentity_%s"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)
    );
    const FString PackageName = TEXT("/Game/DccMcpAutomation/") + AssetName;
    const FString Filename = FPackageName::LongPackageNameToFilename(
        PackageName,
        FPackageName::GetAssetPackageExtension()
    );
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26
    UPackage* Package = CreatePackage(nullptr, *PackageName);
#else
    UPackage* Package = CreatePackage(*PackageName);
#endif
    UMaterialInstanceConstant* Instance = NewObject<UMaterialInstanceConstant>(
        Package,
        FName(*AssetName),
        RF_Public | RF_Standalone | RF_Transactional
    );
    if (!Package || !Instance)
    {
        AddError(TEXT("Failed to create the automation Material Instance."));
        return false;
    }

    const FName ParameterName(TEXT("SharedParameter"));
#if ENGINE_MAJOR_VERSION > 4 || ENGINE_MINOR_VERSION > 18
    FScalarParameterValue LayerOverride;
    LayerOverride.ParameterInfo = FMaterialParameterInfo(
        ParameterName,
        EMaterialParameterAssociation::LayerParameter,
        0
    );
    LayerOverride.ParameterValue = 0.5f;
    Instance->ScalarParameterValues.Add(LayerOverride);
#endif
    Package->MarkPackageDirty();
    if (!SaveAutomationAsset(Instance, Filename) || Package->IsDirty())
    {
        AddError(TEXT("Failed to save the baseline automation Material Instance."));
        IFileManager::Get().Delete(*Filename, false, true, true);
        return false;
    }

    TMap<FString, float> ScalarParameters;
    ScalarParameters.Add(ParameterName.ToString(), 0.5f);
    const TMap<FString, FLinearColor> VectorParameters;
    const TMap<FString, UTexture*> TextureParameters;

    const auto ParseResult = [this](const FString& Payload, bool ExpectedChanged)
    {
        TSharedPtr<FJsonObject> Result;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Payload);
        bool bSuccess = false;
        bool bChanged = !ExpectedChanged;
        bool bVerified = false;
        bool bPackageDirty = true;
        const bool bValid = FJsonSerializer::Deserialize(Reader, Result) && Result.IsValid()
            && Result->TryGetBoolField(TEXT("success"), bSuccess)
            && Result->TryGetBoolField(TEXT("changed"), bChanged)
            && Result->TryGetBoolField(TEXT("verified"), bVerified)
            && Result->TryGetBoolField(TEXT("package_dirty"), bPackageDirty);
        TestTrue(TEXT("Material Instance bridge returned valid JSON"), bValid);
        TestTrue(TEXT("Material Instance bridge reported success"), bSuccess);
        TestEqual(TEXT("Material Instance bridge reported the expected change state"), bChanged, ExpectedChanged);
        TestTrue(TEXT("Material Instance bridge verified the override"), bVerified);
        TestFalse(TEXT("Saved Material Instance package is clean"), bPackageDirty);
        return bValid && bSuccess && bChanged == ExpectedChanged && bVerified && !bPackageDirty;
    };

    bool bPassed = ParseResult(
        UDccMcpAutomationLibrary::ConfigureMaterialInstanceParameters(
            Instance,
            ScalarParameters,
            VectorParameters,
            TextureParameters
        ),
        true
    );

#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION <= 18
    const bool bHasGlobalOverride = Instance->ScalarParameterValues.ContainsByPredicate(
        [ParameterName](const FScalarParameterValue& Value)
        {
            return Value.ParameterName == ParameterName && FMath::IsNearlyEqual(Value.ParameterValue, 0.5f);
        }
    );
#else
    const FMaterialParameterInfo ExpectedInfo(ParameterName);
    const bool bHasGlobalOverride = Instance->ScalarParameterValues.ContainsByPredicate(
        [ExpectedInfo](const FScalarParameterValue& Value)
        {
            return Value.ParameterInfo == ExpectedInfo && FMath::IsNearlyEqual(Value.ParameterValue, 0.5f);
        }
    );
#endif
    TestTrue(TEXT("The requested global parameter override exists"), bHasGlobalOverride);
    bPassed &= bHasGlobalOverride;

    bPassed &= ParseResult(
        UDccMcpAutomationLibrary::ConfigureMaterialInstanceParameters(
            Instance,
            ScalarParameters,
            VectorParameters,
            TextureParameters
        ),
        false
    );

    Package->SetDirtyFlag(false);
    if (!IFileManager::Get().Delete(*Filename, false, true, true))
    {
        AddError(TEXT("Failed to remove the automation Material Instance package."));
        bPassed = false;
    }
    return bPassed;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpMaterialInstanceTransientTextureTest,
    "DccMcp.Smoke.MaterialInstanceTransientTexture",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpMaterialInstanceTransientTextureTest::RunTest(const FString& Parameters)
{
    const FString AssetName = FString::Printf(
        TEXT("MI_DccMcpTransientTexture_%s"),
        *FGuid::NewGuid().ToString(EGuidFormats::Digits)
    );
    const FString PackageName = TEXT("/Game/DccMcpAutomation/") + AssetName;
    const FString Filename = FPackageName::LongPackageNameToFilename(
        PackageName,
        FPackageName::GetAssetPackageExtension()
    );
#if ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION < 26
    UPackage* Package = CreatePackage(nullptr, *PackageName);
#else
    UPackage* Package = CreatePackage(*PackageName);
#endif
    UMaterialInstanceConstant* Instance = NewObject<UMaterialInstanceConstant>(
        Package,
        FName(*AssetName),
        RF_Public | RF_Standalone | RF_Transactional
    );
    UTexture2D* TransientTexture = NewObject<UTexture2D>(GetTransientPackage());
    if (!Package || !Instance || !TransientTexture)
    {
        AddError(TEXT("Failed to create the transient-texture automation inputs."));
        return false;
    }
    Package->MarkPackageDirty();
    if (!SaveAutomationAsset(Instance, Filename) || Package->IsDirty())
    {
        AddError(TEXT("Failed to save the baseline transient-texture Material Instance."));
        IFileManager::Get().Delete(*Filename, false, true, true);
        return false;
    }

    const TMap<FString, float> ScalarParameters;
    const TMap<FString, FLinearColor> VectorParameters;
    TMap<FString, UTexture*> TextureParameters;
    TextureParameters.Add(TEXT("TransientTexture"), TransientTexture);
    const FString Payload = UDccMcpAutomationLibrary::ConfigureMaterialInstanceParameters(
        Instance,
        ScalarParameters,
        VectorParameters,
        TextureParameters
    );

    TSharedPtr<FJsonObject> Result;
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Payload);
    bool bSuccess = true;
    FString ErrorCode;
    const bool bValid = FJsonSerializer::Deserialize(Reader, Result) && Result.IsValid()
        && Result->TryGetBoolField(TEXT("success"), bSuccess)
        && Result->TryGetStringField(TEXT("error_code"), ErrorCode);
    TestTrue(TEXT("Transient texture rejection returned valid JSON"), bValid);
    TestFalse(TEXT("Transient texture is rejected"), bSuccess);
    TestEqual(TEXT("Transient texture uses the input validation error"), ErrorCode, FString(TEXT("invalid_texture_parameter")));
    TestFalse(TEXT("Rejected transient texture leaves the package clean"), Package->IsDirty());
    TestEqual(TEXT("Rejected transient texture leaves no override"), Instance->TextureParameterValues.Num(), 0);

    Package->SetDirtyFlag(false);
    bool bPassed = bValid && !bSuccess && ErrorCode == TEXT("invalid_texture_parameter")
        && !Package->IsDirty() && Instance->TextureParameterValues.Num() == 0;
    if (!IFileManager::Get().Delete(*Filename, false, true, true))
    {
        AddError(TEXT("Failed to remove the transient-texture automation package."));
        bPassed = false;
    }
    return bPassed;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpEditorViewportFocusTest,
    "DccMcp.Smoke.EditorViewportFocus",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpEditorViewportFocusTest::RunTest(const FString& Parameters)
{
    TSharedPtr<FJsonObject> Result;
    const FString Payload = UDccMcpAutomationLibrary::FocusLevelEditorViewport();
    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Payload);
    bool bSuccess = false;
    bool bLevelEditorActivated = false;
    bool bViewportFocused = false;
    bool bPostconditionMet = false;
    const bool bValid = FJsonSerializer::Deserialize(Reader, Result) && Result.IsValid()
        && Result->TryGetBoolField(TEXT("success"), bSuccess)
        && Result->TryGetBoolField(TEXT("level_editor_activated"), bLevelEditorActivated)
        && Result->TryGetBoolField(TEXT("viewport_focused"), bViewportFocused)
        && Result->TryGetBoolField(TEXT("postcondition_met"), bPostconditionMet)
        && Result->HasTypedField<EJson::Array>(TEXT("close_requested_items"))
        && Result->HasTypedField<EJson::Array>(TEXT("closed_items"))
        && Result->HasTypedField<EJson::Array>(TEXT("remaining_log_tabs"));
    TestTrue(TEXT("Editor viewport focus returned structured JSON"), bValid);
    if (!bValid)
    {
        AddError(FString::Printf(TEXT("Invalid editor viewport focus payload: %s"), *Payload));
        return false;
    }

    const TArray<TSharedPtr<FJsonValue>>& RemainingLogTabs = Result->GetArrayField(TEXT("remaining_log_tabs"));
    const bool bExpectedPostcondition = RemainingLogTabs.Num() == 0
        && bLevelEditorActivated
        && bViewportFocused;
    TestEqual(TEXT("No requested log tab remains open"), RemainingLogTabs.Num(), 0);
    TestTrue(TEXT("Level Editor tab is active"), bLevelEditorActivated);
    TestEqual(
        TEXT("Success matches the verified editor viewport postcondition"),
        bSuccess,
        bExpectedPostcondition
    );
    TestEqual(
        TEXT("Reported postcondition matches observed structured fields"),
        bPostconditionMet,
        bExpectedPostcondition
    );
    if (!bSuccess)
    {
        FString ErrorCode;
        const bool bHasErrorCode = Result->TryGetStringField(TEXT("error_code"), ErrorCode)
            && !ErrorCode.IsEmpty();
        TestTrue(TEXT("A failed focus attempt reports an error code"), bHasErrorCode);
        return RemainingLogTabs.Num() == 0
            && bLevelEditorActivated
            && bHasErrorCode
            && !bPostconditionMet;
    }
    return RemainingLogTabs.Num() == 0
        && bLevelEditorActivated
        && bViewportFocused
        && bPostconditionMet;
}

#endif // WITH_DEV_AUTOMATION_TESTS
