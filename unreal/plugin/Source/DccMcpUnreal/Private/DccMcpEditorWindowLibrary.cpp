#include "DccMcpEditorWindowLibrary.h"

#include "CoreGlobals.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

#if WITH_EDITOR && PLATFORM_WINDOWS
#include "Runtime/Launch/Resources/Version.h"
#include "GenericPlatform/GenericWindow.h"
#include "HAL/PlatformProcess.h"
#include "Interfaces/IMainFrameModule.h"
#include "Modules/ModuleManager.h"
#include "Widgets/SWindow.h"
#include "Windows/WindowsHWrapper.h"
#endif

namespace
{
FString IdentityResult(const FString& Reason, uint32 HostPid = 0,
    uint32 WindowPid = 0, const FString& WindowHandle = FString())
{
    TSharedRef<FJsonObject> Json = MakeShareable(new FJsonObject());
    Json->SetStringField(TEXT("schema"), TEXT("dcc-unreal-editor-main-frame/v1"));
    const bool bSuccess = Reason == TEXT("ok");
    Json->SetBoolField(TEXT("success"), bSuccess);
    Json->SetStringField(TEXT("reason"), Reason);
    if (bSuccess)
    {
        // A uint32 PID is exact in JSON's double representation; HWND is not.
        Json->SetNumberField(TEXT("host_pid"), HostPid);
        Json->SetNumberField(TEXT("window_pid"), WindowPid);
        Json->SetStringField(TEXT("window_handle"), WindowHandle);
    }
    FString Output;
    FJsonSerializer::Serialize(Json, TJsonWriterFactory<>::Create(&Output));
    return Output;
}
}

FString UDccMcpEditorWindowLibrary::GetMainFrameIdentityJson()
{
    if (!IsInGameThread()) return IdentityResult(TEXT("not_game_thread"));
#if !WITH_EDITOR
    return IdentityResult(TEXT("not_editor"));
#elif !PLATFORM_WINDOWS
    return IdentityResult(TEXT("unsupported_platform"));
#else
    // GetModulePtr never loads the module or creates a MainFrame window.
    IMainFrameModule* MainFrame = FModuleManager::GetModulePtr<IMainFrameModule>(TEXT("MainFrame"));
    if (!MainFrame || !MainFrame->IsWindowInitialized())
        return IdentityResult(TEXT("main_frame_unavailable"));
#if ENGINE_MAJOR_VERSION >= 5
    if (MainFrame->IsRecreatingDefaultMainFrame())
        return IdentityResult(TEXT("main_frame_recreating"));
#endif
    const TSharedPtr<SWindow> ParentWindow = MainFrame->GetParentWindow();
    if (!ParentWindow.IsValid()) return IdentityResult(TEXT("main_frame_window_unavailable"));
    const TSharedPtr<FGenericWindow> NativeWindow = ParentWindow->GetNativeWindow();
    if (!NativeWindow.IsValid()) return IdentityResult(TEXT("native_window_unavailable"));
    void* OsHandle = NativeWindow->GetOSWindowHandle();
    if (!OsHandle) return IdentityResult(TEXT("os_window_unavailable"));
    const HWND Handle = static_cast<HWND>(OsHandle);
    if (!::IsWindow(Handle)) return IdentityResult(TEXT("invalid_window"));
    DWORD WindowPid = 0;
    if (!::GetWindowThreadProcessId(Handle, &WindowPid) || !WindowPid)
        return IdentityResult(TEXT("window_pid_unavailable"));
    const uint32 HostPid = FPlatformProcess::GetCurrentProcessId();
    if (!HostPid) return IdentityResult(TEXT("host_pid_unavailable"));
    if (WindowPid != HostPid) return IdentityResult(TEXT("foreign_process_window"));
    if (!::IsWindow(Handle)) return IdentityResult(TEXT("window_changed"));
    const FString WindowHandle = FString::Printf(TEXT("%llu"),
        static_cast<uint64>(reinterpret_cast<UPTRINT>(Handle)));
    return IdentityResult(TEXT("ok"), HostPid, WindowPid, WindowHandle);
#endif
}
