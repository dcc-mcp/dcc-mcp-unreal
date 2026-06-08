#include "HAL/FileManager.h"
#include "HAL/PlatformMisc.h"
#include "IPythonScriptPlugin.h"
#include "Interfaces/IPluginManager.h"
#include "Dom/JsonObject.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace DccMcpUnrealAutomation
{
FString NormalizeForPython(const FString& Path)
{
    FString Normalized = FPaths::ConvertRelativePathToFull(Path);
    FPaths::NormalizeFilename(Normalized);
    Normalized.ReplaceInline(TEXT("'"), TEXT("\\'"));
    return Normalized;
}

FString GetResultPath()
{
    FString EnvResultPath = FPlatformMisc::GetEnvironmentVariable(TEXT("DCC_MCP_UNREAL_TEST_RESULT"));
    if (!EnvResultPath.IsEmpty())
    {
        return EnvResultPath;
    }
    return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Automation"), TEXT("dcc_mcp_unreal_native_smoke.json"));
}

bool LoadResultJson(const FString& ResultPath, TSharedPtr<FJsonObject>& OutJson, FString& OutError)
{
    FString JsonText;
    if (!FFileHelper::LoadFileToString(JsonText, *ResultPath))
    {
        OutError = FString::Printf(TEXT("Smoke result file was not written: %s"), *ResultPath);
        return false;
    }

    const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
    if (!FJsonSerializer::Deserialize(Reader, OutJson) || !OutJson.IsValid())
    {
        OutError = FString::Printf(TEXT("Smoke result JSON could not be parsed: %s"), *ResultPath);
        return false;
    }

    return true;
}
} // namespace DccMcpUnrealAutomation

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FDccMcpUnrealNativeSmokeTest,
    "DccMcp.Smoke.ServerStarts",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter
)

bool FDccMcpUnrealNativeSmokeTest::RunTest(const FString& Parameters)
{
    const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("DccMcpUnreal"));
    if (!Plugin.IsValid())
    {
        AddError(TEXT("DccMcpUnreal plugin is not registered with IPluginManager."));
        return false;
    }

    const FString ResultPath = DccMcpUnrealAutomation::GetResultPath();
    const FString ResultDir = FPaths::GetPath(ResultPath);
    IFileManager::Get().MakeDirectory(*ResultDir, true);
    IFileManager::Get().Delete(*ResultPath, false, true);

    IPythonScriptPlugin& PythonScriptPlugin =
        FModuleManager::LoadModuleChecked<IPythonScriptPlugin>(TEXT("PythonScriptPlugin"));
    if (!PythonScriptPlugin.IsPythonAvailable())
    {
        AddError(TEXT("PythonScriptPlugin is loaded but Python support is unavailable."));
        return false;
    }

    const FString PythonResultPath = DccMcpUnrealAutomation::NormalizeForPython(ResultPath);
    const FString Command = FString::Printf(
        TEXT("import dcc_mcp_unreal_automation\n")
        TEXT("dcc_mcp_unreal_automation.run_smoke(result_path='%s', raise_on_failure=False)"),
        *PythonResultPath
    );

    const bool bPythonRan = PythonScriptPlugin.ExecPythonCommand(*Command);
    if (!bPythonRan)
    {
        AddError(TEXT("PythonScriptPlugin failed while executing dcc_mcp_unreal_automation.run_smoke."));
    }

    TSharedPtr<FJsonObject> ResultJson;
    FString ResultError;
    if (!DccMcpUnrealAutomation::LoadResultJson(ResultPath, ResultJson, ResultError))
    {
        AddError(ResultError);
        return false;
    }

    bool bSuccess = false;
    if (!ResultJson->TryGetBoolField(TEXT("success"), bSuccess) || !bSuccess)
    {
        FString Error;
        ResultJson->TryGetStringField(TEXT("error"), Error);
        AddError(FString::Printf(TEXT("DCC MCP native smoke failed: %s"), *Error));
        return false;
    }

    FString McpUrl;
    if (ResultJson->TryGetStringField(TEXT("mcp_url"), McpUrl))
    {
        AddInfo(FString::Printf(TEXT("MCP URL: %s"), *McpUrl));
    }

    int32 SkillCount = 0;
    if (ResultJson->TryGetNumberField(TEXT("skill_count"), SkillCount))
    {
        AddInfo(FString::Printf(TEXT("Skill count: %d"), SkillCount));
    }

    int32 ToolCount = 0;
    if (ResultJson->TryGetNumberField(TEXT("tool_count"), ToolCount))
    {
        AddInfo(FString::Printf(TEXT("Tool count: %d"), ToolCount));
    }

    return bPythonRan;
}

#endif // WITH_DEV_AUTOMATION_TESTS
