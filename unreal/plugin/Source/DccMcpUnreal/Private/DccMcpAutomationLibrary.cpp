#include "DccMcpAutomationLibrary.h"

#include "Dom/JsonObject.h"
#include "Interfaces/IPluginManager.h"
#include "Misc/AutomationTest.h"
#include "Modules/ModuleManager.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Runtime/Launch/Resources/Version.h"
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
} // namespace

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

    return SerializeJson(Root);
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
