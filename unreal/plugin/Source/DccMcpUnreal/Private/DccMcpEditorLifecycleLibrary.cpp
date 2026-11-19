#include "DccMcpEditorLifecycleLibrary.h"

#include "Runtime/Launch/Resources/Version.h"
#include "Containers/Ticker.h"
#include "Dom/JsonObject.h"
#include "Editor.h"
#include "FileHelpers.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Interfaces/IMainFrameModule.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/DateTime.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Modules/ModuleManager.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/GarbageCollection.h"
#include "UObject/UObjectGlobals.h"
#if PLATFORM_WINDOWS
#include "Windows/WindowsHWrapper.h"
#endif

namespace
{
#if ENGINE_MAJOR_VERSION >= 5
using FLifecycleTicker = FTSTicker;
using FLifecycleTickerHandle = FTSTicker::FDelegateHandle;
#else
using FLifecycleTicker = FTicker;
using FLifecycleTickerHandle = FDelegateHandle;
#endif
struct FCloseBinding
{
    bool bEnabled = false;
    FString Owner, Session, Nonce, Pid, Creation, Project;
    FString RequestId, State = TEXT("disabled"), Reason;
    int64 ExpiresUnixMs = 0;
    double ExpiresMonotonic = 0;
    FLifecycleTickerHandle Tick;
};
FCloseBinding OwnedCloseBinding;

FString Environment(const TCHAR* Name)
{
#if ENGINE_MAJOR_VERSION >= 5
    return FPlatformMisc::GetEnvironmentVariable(Name);
#else
    TCHAR Buffer[1024] = {};
    FPlatformMisc::GetEnvironmentVariable(Name, Buffer, 1024);
    return FString(Buffer);
#endif
}

bool IsHex(const FString& Value, int32 Length)
{
    if (Value.Len() != Length) return false;
    for (TCHAR C : Value)
        if (!((C >= '0' && C <= '9') || (C >= 'a' && C <= 'f'))) return false;
    return true;
}

bool IsIdentifier(const FString& Value)
{
    if (Value.IsEmpty() || Value.Len() > 128) return false;
    for (TCHAR C : Value)
        if (!((C >= 'a' && C <= 'z') || (C >= 'A' && C <= 'Z')
            || (C >= '0' && C <= '9') || C == '-' || C == '_' || C == '.')) return false;
    return true;
}

FString ProjectFile()
{
    FString Path = FPaths::ConvertRelativePathToFull(FPaths::GetProjectFilePath());
    FPaths::NormalizeFilename(Path);
    FPaths::CollapseRelativeDirectories(Path);
    return Path;
}

FString ProcessCreation()
{
#if PLATFORM_WINDOWS
    FILETIME Creation = {}, Exit = {}, Kernel = {}, User = {};
    if (::GetProcessTimes(::GetCurrentProcess(), &Creation, &Exit, &Kernel, &User))
        return FString::Printf(TEXT("%llu"),
            (static_cast<uint64>(Creation.dwHighDateTime) << 32) | Creation.dwLowDateTime);
#endif
    return FString();
}

int64 UnixMs()
{
    const FDateTime Now = FDateTime::UtcNow();
    return Now.ToUnixTimestamp() * 1000 + Now.GetMillisecond();
}

FString UnsafeReason()
{
    if (!IsInGameThread()) return TEXT("not_game_thread");
    if (!OwnedCloseBinding.bEnabled) return TEXT("launch_opt_in_missing");
    if (OwnedCloseBinding.Pid != FString::Printf(TEXT("%u"), FPlatformProcess::GetCurrentProcessId())
        || OwnedCloseBinding.Creation != ProcessCreation() || OwnedCloseBinding.Project != ProjectFile())
        return TEXT("host_binding_changed");
    if (IsRunningCommandlet() || FApp::IsUnattended()) return TEXT("unattended_or_commandlet");
    if (!GEditor) return TEXT("editor_unavailable");
    if (GIsSavingPackage || IsLoading() || IsGarbageCollecting() || GIsSlowTask)
        return TEXT("saving_loading_gc_or_slow_task");
    if (!FSlateApplication::IsInitialized() || !FSlateApplication::Get().IsNormalExecution())
        return TEXT("slate_unavailable_or_debugging");
    if (FSlateApplication::Get().GetActiveModalWindow().IsValid()) return TEXT("modal_window");
#if ENGINE_MAJOR_VERSION > 4 || (ENGINE_MAJOR_VERSION == 4 && ENGINE_MINOR_VERSION >= 25)
    if (GEditor->IsPlaySessionInProgress()) return TEXT("pie_active_or_queued");
#else
    if (GEditor->PlayWorld || GEditor->bIsSimulatingInEditor || GEditor->bIsPlayWorldQueued
        || GEditor->bIsSimulateInEditorQueued || GEditor->bIsToggleBetweenPIEandSIEQueued
        || GEditor->bRequestEndPlayMapQueued) return TEXT("pie_active_or_queued");
#endif
    if (GEditor->IsLightingBuildCurrentlyRunning()) return TEXT("lighting_build");
    IMainFrameModule* MainFrame = FModuleManager::GetModulePtr<IMainFrameModule>(TEXT("MainFrame"));
    if (!MainFrame || !MainFrame->IsWindowInitialized()) return TEXT("main_frame_unavailable");
#if ENGINE_MAJOR_VERSION >= 5
    if (MainFrame->IsRecreatingDefaultMainFrame()) return TEXT("main_frame_recreating");
#endif
    TArray<UPackage*> Dirty;
    FEditorFileUtils::GetDirtyWorldPackages(Dirty);
    if (Dirty.Num()) return TEXT("dirty_world_packages");
    FEditorFileUtils::GetDirtyContentPackages(Dirty);
    return Dirty.Num() ? TEXT("dirty_content_packages") : FString();
}

FString Result(const FString& State, const FString& Reason = FString())
{
    TSharedRef<FJsonObject> Json = MakeShareable(new FJsonObject());
    Json->SetStringField(TEXT("schema"), TEXT("dcc-unreal-editor-close/v1"));
    Json->SetStringField(TEXT("state"), State);
    Json->SetStringField(TEXT("reason"), Reason);
    Json->SetBoolField(TEXT("process_exit_verified"), false);
    Json->SetBoolField(TEXT("response_flush_verified"), false);
    if (IsInGameThread())
    {
        Json->SetBoolField(TEXT("enabled"), OwnedCloseBinding.bEnabled);
        Json->SetStringField(TEXT("owner"), OwnedCloseBinding.Owner);
        Json->SetStringField(TEXT("session"), OwnedCloseBinding.Session);
        Json->SetStringField(TEXT("host_pid"), OwnedCloseBinding.Pid);
        Json->SetStringField(TEXT("creation_filetime"), OwnedCloseBinding.Creation);
        Json->SetStringField(TEXT("project_file"), OwnedCloseBinding.Project);
        Json->SetStringField(TEXT("request_id"), OwnedCloseBinding.RequestId);
    }
    FString Output;
    FJsonSerializer::Serialize(Json, TJsonWriterFactory<>::Create(&Output));
    return Output;
}

bool GuardMatches(const TSharedPtr<FJsonObject>& Guard, const FCloseBinding& ExpectedBinding,
    int64 NowUnixMs, FString& RequestId, int64& Expiry)
{
    const TCHAR* Fields[] = {TEXT("instance_id"), TEXT("owner"), TEXT("session"), TEXT("host_pid"),
        TEXT("creation_filetime"), TEXT("project_file"), TEXT("request_id"), TEXT("expires_unix_ms")};
    if (!Guard.IsValid() || Guard->Values.Num() != 9) return false;
    TArray<FString> Values;
    for (const TCHAR* Field : Fields)
    {
        FString Value;
        if (!Guard->TryGetStringField(Field, Value) || Value.Contains(TEXT("\n"))
            || Value.Contains(TEXT("\r")) || Value.Len() > 4096) return false;
        Values.Add(Value);
    }
    FGuid Instance, Request;
    if (!FGuid::Parse(Values[0], Instance) || !FGuid::Parse(Values[6], Request)
        || Values[1] != ExpectedBinding.Owner || Values[2] != ExpectedBinding.Session
        || Values[3] != ExpectedBinding.Pid || Values[4] != ExpectedBinding.Creation || Values[5] != ExpectedBinding.Project)
        return false;
    if (Values[7].Len() != 13) return false;
    for (TCHAR C : Values[7]) if (C < '0' || C > '9') return false;
    Expiry = FCString::Atoi64(*Values[7]);
    const int64 Remaining = Expiry - NowUnixMs;
    if (Remaining <= 0 || Remaining > 2000) return false;
    FString Proof;
    if (!Guard->TryGetStringField(TEXT("proof"), Proof) || !IsHex(Proof, 40)) return false;
    const FString Message = TEXT("dcc-unreal-editor-close/v1\n") + FString::Join(Values, TEXT("\n"));
    FTCHARToUTF8 Key(*ExpectedBinding.Nonce), Data(*Message);
    uint8 Digest[FSHA1::DigestSize];
    FSHA1::HMACBuffer(Key.Get(), Key.Length(), Data.Get(), Data.Length(), Digest);
    const FString Expected = BytesToHex(Digest, FSHA1::DigestSize).ToLower();
    uint32 Difference = 0;
    for (int32 Index = 0; Index < Expected.Len(); ++Index) Difference |= Expected[Index] ^ Proof[Index];
    RequestId = Values[6];
    return Difference == 0;
}
}

#if WITH_DEV_AUTOMATION_TESTS
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FDccMcpEditorCloseGuardTest,
    "DccMcp.Lifecycle.GuardProofAndExpiry", EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

bool FDccMcpEditorCloseGuardTest::RunTest(const FString&)
{
    // Published synthetic vector; never reads or changes the live launch capability.
    FCloseBinding Expected;
    Expected.Owner = TEXT("test-owner");
    Expected.Session = TEXT("test-session");
    Expected.Nonce = FString::ChrN(64, 'a');
    Expected.Pid = TEXT("4242");
    Expected.Creation = TEXT("134360052743565450");
    Expected.Project = TEXT("F:/owned/Test.uproject");
    TSharedPtr<FJsonObject> Guard = MakeShareable(new FJsonObject());
    Guard->SetStringField(TEXT("instance_id"), TEXT("11111111-1111-4111-8111-111111111111"));
    Guard->SetStringField(TEXT("owner"), Expected.Owner);
    Guard->SetStringField(TEXT("session"), Expected.Session);
    Guard->SetStringField(TEXT("host_pid"), Expected.Pid);
    Guard->SetStringField(TEXT("creation_filetime"), Expected.Creation);
    Guard->SetStringField(TEXT("project_file"), Expected.Project);
    Guard->SetStringField(TEXT("request_id"), TEXT("22222222-2222-4222-8222-222222222222"));
    Guard->SetStringField(TEXT("expires_unix_ms"), TEXT("1791532801000"));
    Guard->SetStringField(TEXT("proof"), TEXT("f410390454412918de6820b24780804183b5d70e"));
    FString RequestId;
    int64 Expiry = 0;
    TestTrue(TEXT("Matches Python hmac.new synthetic vector"), GuardMatches(Guard, Expected, 1791532800000LL, RequestId, Expiry));
    TestEqual(TEXT("Expiry remains integral"), Expiry, 1791532801000LL);
    TestFalse(TEXT("Expired proof refuses"), GuardMatches(Guard, Expected, 1791532801000LL, RequestId, Expiry));
    TestFalse(TEXT("Proof cannot reserve a longer deadline"), GuardMatches(Guard, Expected, 1791532798999LL, RequestId, Expiry));
    const TCHAR* Fields[] = {TEXT("instance_id"), TEXT("owner"), TEXT("session"), TEXT("host_pid"),
        TEXT("creation_filetime"), TEXT("project_file"), TEXT("request_id"), TEXT("expires_unix_ms"), TEXT("proof")};
    const TCHAR* Changes[] = {TEXT("33333333-3333-4333-8333-333333333333"), TEXT("other-owner"),
        TEXT("other-session"), TEXT("4243"), TEXT("134360052743565451"), TEXT("F:/other/Test.uproject"),
        TEXT("44444444-4444-4444-8444-444444444444"), TEXT("1791532801001"),
        TEXT("0000000000000000000000000000000000000000")};
    for (int32 Index = 0; Index < static_cast<int32>(sizeof(Fields) / sizeof(Fields[0])); ++Index)
    {
        const FString Before = Guard->GetStringField(Fields[Index]);
        Guard->SetStringField(Fields[Index], Changes[Index]);
        TestFalse(TEXT("Every field is bound to the proof/launch"), GuardMatches(Guard, Expected, 1791532800000LL, RequestId, Expiry));
        Guard->SetStringField(Fields[Index], Before);
    }
    Expected.Nonce[0] = 'b';
    TestFalse(TEXT("A different launch secret refuses"), GuardMatches(Guard, Expected, 1791532800000LL, RequestId, Expiry));
    Expected.Nonce[0] = 'a';
    Guard->SetStringField(TEXT("unexpected"), TEXT("ignored would be unsafe"));
    TestFalse(TEXT("Unknown fields refuse"), GuardMatches(Guard, Expected, 1791532800000LL, RequestId, Expiry));
    return true;
}
#endif

void DccMcpInitializeEditorLifecycle()
{
    OwnedCloseBinding = FCloseBinding();
    // Capture only at plugin startup; later caller fields cannot grant ownership.
    OwnedCloseBinding.Owner = Environment(TEXT("DCC_MCP_UNREAL_CLOSE_OWNER"));
    OwnedCloseBinding.Session = Environment(TEXT("DCC_MCP_UNREAL_CLOSE_SESSION"));
    OwnedCloseBinding.Nonce = Environment(TEXT("DCC_MCP_UNREAL_CLOSE_NONCE"));
    FPlatformMisc::SetEnvironmentVar(TEXT("DCC_MCP_UNREAL_CLOSE_NONCE"), TEXT(""));
    OwnedCloseBinding.Pid = FString::Printf(TEXT("%u"), FPlatformProcess::GetCurrentProcessId());
    OwnedCloseBinding.Creation = ProcessCreation();
    OwnedCloseBinding.Project = ProjectFile();
    OwnedCloseBinding.bEnabled = IsInGameThread() && IsIdentifier(OwnedCloseBinding.Owner) && IsIdentifier(OwnedCloseBinding.Session)
        && IsHex(OwnedCloseBinding.Nonce, 64) && !OwnedCloseBinding.Creation.IsEmpty()
        && !FPaths::GetProjectFilePath().IsEmpty() && FPaths::FileExists(OwnedCloseBinding.Project);
    OwnedCloseBinding.State = OwnedCloseBinding.bEnabled ? TEXT("idle") : TEXT("disabled");
    if (!OwnedCloseBinding.bEnabled) OwnedCloseBinding.Nonce.Empty();
}

void DccMcpShutdownEditorLifecycle()
{
    if (OwnedCloseBinding.Tick.IsValid()) FLifecycleTicker::GetCoreTicker().RemoveTicker(OwnedCloseBinding.Tick);
    OwnedCloseBinding = FCloseBinding();
}

FString UDccMcpEditorLifecycleLibrary::InspectEditorCloseJson()
{
    if (!IsInGameThread()) return Result(TEXT("refused"), TEXT("not_game_thread"));
    const FString Reason = UnsafeReason();
    return Result(Reason.IsEmpty() ? TEXT("ready") : TEXT("refused"), Reason);
}

FString UDccMcpEditorLifecycleLibrary::GetEditorCloseStatusJson()
{
    if (!IsInGameThread()) return Result(TEXT("refused"), TEXT("not_game_thread"));
    return Result(OwnedCloseBinding.State, OwnedCloseBinding.Reason);
}

FString UDccMcpEditorLifecycleLibrary::RequestEditorCloseJson(const FString& GuardJson)
{
    if (!IsInGameThread()) return Result(TEXT("refused"), TEXT("not_game_thread"));
    if (!OwnedCloseBinding.bEnabled) return Result(TEXT("refused"), TEXT("launch_opt_in_missing"));
    TSharedPtr<FJsonObject> Guard;
    if (GuardJson.Len() > 8192 || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(GuardJson), Guard))
        return Result(TEXT("refused"), TEXT("invalid_guard"));
    FString RequestId;
    int64 Expiry = 0;
    if (!GuardMatches(Guard, OwnedCloseBinding, UnixMs(), RequestId, Expiry))
        return Result(TEXT("refused"), TEXT("guard_mismatch_or_expired"));
    if (!OwnedCloseBinding.RequestId.IsEmpty())
        return RequestId == OwnedCloseBinding.RequestId ? Result(OwnedCloseBinding.State, OwnedCloseBinding.Reason)
            : Result(TEXT("refused"), TEXT("request_already_consumed"));
    const FString Reason = UnsafeReason();
    if (!Reason.IsEmpty()) return Result(TEXT("refused"), Reason);
    OwnedCloseBinding.RequestId = RequestId;
    OwnedCloseBinding.ExpiresUnixMs = Expiry;
    OwnedCloseBinding.ExpiresMonotonic = FPlatformTime::Seconds() + (Expiry - UnixMs()) / 1000.0;
    OwnedCloseBinding.State = TEXT("scheduled");
    // One tick leaves the dispatch stack. It does not prove HTTP response flush.
    OwnedCloseBinding.Tick = FLifecycleTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([](float)
    {
        if (!IsInGameThread()) return false;
        OwnedCloseBinding.Tick.Reset();
        if (UnixMs() >= OwnedCloseBinding.ExpiresUnixMs || FPlatformTime::Seconds() >= OwnedCloseBinding.ExpiresMonotonic)
        {
            OwnedCloseBinding.State = TEXT("expired");
            return false;
        }
        OwnedCloseBinding.Reason = UnsafeReason();
        if (!OwnedCloseBinding.Reason.IsEmpty())
        {
            OwnedCloseBinding.State = TEXT("refused_at_execution");
            return false;
        }
        OwnedCloseBinding.State = TEXT("close_requested");
        FModuleManager::GetModulePtr<IMainFrameModule>(TEXT("MainFrame"))->RequestCloseEditor();
        return false;
    }), 0.25f);
    return Result(OwnedCloseBinding.State);
}
