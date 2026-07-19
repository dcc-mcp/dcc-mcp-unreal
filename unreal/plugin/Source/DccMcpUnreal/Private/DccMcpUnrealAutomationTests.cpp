#include "DccMcpAutomationLibrary.h"

#include "Dom/JsonObject.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

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
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
