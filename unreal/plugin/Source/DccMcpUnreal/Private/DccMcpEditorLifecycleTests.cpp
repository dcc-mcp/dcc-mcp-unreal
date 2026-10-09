#include "DccMcpEditorLifecycleLibrary.h"

#include "Dom/JsonObject.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FDccMcpMalformedEditorCloseTest,
    "DccMcp.Lifecycle.MalformedGuardCannotSchedule",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FDccMcpMalformedEditorCloseTest::RunTest(const FString&)
{
    const FString Before = UDccMcpEditorLifecycleLibrary::GetEditorCloseStatusJson();
    const TCHAR* Invalid[] = {TEXT(""), TEXT("{}"), TEXT("null"), TEXT("[]"),
        TEXT("{\"owner\":\"caller-cannot-opt-in\"}")};
    for (const TCHAR* Guard : Invalid)
    {
        TSharedPtr<FJsonObject> Result;
        TestTrue(TEXT("Native refusal is JSON"), FJsonSerializer::Deserialize(
            TJsonReaderFactory<>::Create(UDccMcpEditorLifecycleLibrary::RequestEditorCloseJson(Guard)), Result));
        if (!Result.IsValid()) return false;
        TestEqual(TEXT("Malformed request is refused"), Result->GetStringField(TEXT("state")), FString(TEXT("refused")));
        TestFalse(TEXT("Does not claim exit"), Result->GetBoolField(TEXT("process_exit_verified")));
    }
    TestEqual(TEXT("Malformed requests do not consume or mutate close state"),
        UDccMcpEditorLifecycleLibrary::GetEditorCloseStatusJson(), Before);
    return true;
}
#endif
