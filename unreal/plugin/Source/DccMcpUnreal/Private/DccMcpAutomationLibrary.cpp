#include "DccMcpAutomationLibrary.h"

#include "Dom/JsonObject.h"
#include "Misc/AutomationTest.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Runtime/Launch/Resources/Version.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

FString UDccMcpAutomationLibrary::ListAutomationTestsJson(const FString& Filter)
{
    FAutomationTestFramework& Framework = FAutomationTestFramework::Get();
    Framework.LoadTestModules();
#if ENGINE_MAJOR_VERSION < 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION < 7)
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

    FString Output;
    const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
        TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Output);
    FJsonSerializer::Serialize(Root, Writer);
    return Output;
}
