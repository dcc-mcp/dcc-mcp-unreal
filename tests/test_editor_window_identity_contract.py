"""Read native source only: never import Unreal or invoke a window API."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "unreal/plugin/Source/DccMcpUnreal"


class EditorWindowIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header = (NATIVE / "Public/DccMcpEditorWindowLibrary.h").read_text(encoding="utf-8")
        cls.source = (NATIVE / "Private/DccMcpEditorWindowLibrary.cpp").read_text(encoding="utf-8")
        cls.body = cls.source.split("FString UDccMcpEditorWindowLibrary::GetMainFrameIdentityJson()", 1)[1]

    def test_only_one_parameterless_identity_function_is_reflected(self):
        self.assertEqual(self.header.count("UFUNCTION("), 1)
        self.assertIn("static FString GetMainFrameIdentityJson();", self.header)
        self.assertIn("DccMcpEditorWindowLibrary.generated.h", self.header)

    def test_unsupported_contexts_fail_before_main_frame_access(self):
        source = self.body
        self.assertLess(source.index("!IsInGameThread()"), source.index("GetModulePtr<"))
        self.assertIn("#if !WITH_EDITOR", source)
        self.assertIn("#elif !PLATFORM_WINDOWS", source)
        for reason in ("not_game_thread", "not_editor", "unsupported_platform"):
            self.assertIn(f'IdentityResult(TEXT("{reason}"))', source)
        self.assertIn("#if WITH_EDITOR && PLATFORM_WINDOWS", self.source)

    def test_loaded_main_frame_is_the_only_window_source(self):
        calls = (
            "GetModulePtr<IMainFrameModule>",
            "IsWindowInitialized()",
            "GetParentWindow()",
            "GetNativeWindow()",
            "GetOSWindowHandle()",
            "::IsWindow(Handle)",
            "::GetWindowThreadProcessId(Handle, &WindowPid)",
        )
        offsets = [self.body.index(call) for call in calls]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("if (!ParentWindow.IsValid())", self.body)
        self.assertIn("if (!NativeWindow.IsValid())", self.body)
        self.assertIn("if (!OsHandle)", self.body)
        self.assertIn("#if ENGINE_MAJOR_VERSION >= 5", self.body)

    def test_live_window_pid_must_match_the_actual_process(self):
        self.assertIn("FPlatformProcess::GetCurrentProcessId()", self.body)
        self.assertIn("if (WindowPid != HostPid)", self.body)
        self.assertIn("|| !WindowPid)", self.body)
        self.assertIn("if (!HostPid)", self.body)
        self.assertEqual(self.body.count("::IsWindow(Handle)"), 2)
        self.assertLess(self.body.index("WindowPid != HostPid"), self.body.index('IdentityResult(TEXT("ok"),'))

    def test_handle_is_a_decimal_string_and_failure_has_no_target_fields(self):
        self.assertIn('TEXT("dcc-unreal-editor-main-frame/v1")', self.source)
        self.assertIn('FString::Printf(TEXT("%llu")', self.body)
        self.assertIn("static_cast<uint64>(reinterpret_cast<UPTRINT>(Handle))", self.body)
        self.assertIn('SetStringField(TEXT("window_handle"), WindowHandle)', self.source)
        self.assertNotIn('SetNumberField(TEXT("window_handle")', self.source)
        branch = self.source.split("if (bSuccess)", 1)[1].split("FString Output;", 1)[0]
        for field in ("host_pid", "window_pid", "window_handle"):
            self.assertIn(f'TEXT("{field}")', branch)
            self.assertEqual(self.source.count(f'TEXT("{field}")'), 1)

    def test_no_mutation_inventory_foreground_content_or_input_primitives(self):
        # The Win32 call allowlist is intentionally smaller than general UI control.
        self.assertEqual(
            set(re.findall(r"(?<![\w:>])::([A-Za-z_]\w*)\s*\(", self.source)), {"IsWindow", "GetWindowThreadProcessId"}
        )
        for forbidden in (
            "LoadModule",
            "GetForegroundWindow",
            "GetActiveWindow",
            "EnumWindows",
            "FindWindow",
            "GetWindowText",
            "SetForegroundWindow",
            "ActivateWindow",
            "BringWindowToTop",
            "SendInput",
            "PostMessage",
            "SendMessage",
            "RequestCloseEditor",
            "GetWindowRect",
            "GetClientRect",
            "Capture",
            "TakeScreenshot",
            "GetProcessTimes",
        ):
            self.assertNotIn(forbidden, self.source)


if __name__ == "__main__":
    unittest.main()
