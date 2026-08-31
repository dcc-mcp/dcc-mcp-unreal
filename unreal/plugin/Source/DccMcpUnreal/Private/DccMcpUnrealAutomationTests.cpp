#include "DccMcpAutomationLibrary.h"

#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Interfaces/IPluginManager.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpressionConstant.h"
#include "Misc/AutomationTest.h"
#include "Misc/Guid.h"
#include "Misc/PackageName.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"
#if ENGINE_MAJOR_VERSION >= 5
#include "UObject/SavePackage.h"
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

namespace
{
bool SaveAutomationMaterial(UMaterial* Material, const FString& Filename)
{
    UPackage* Package = Material ? Material->GetOutermost() : nullptr;
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
    if (!SaveAutomationMaterial(Material, Filename) || Package->IsDirty())
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

#endif // WITH_DEV_AUTOMATION_TESTS
