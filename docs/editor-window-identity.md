# Editor MainFrame identity metadata

`unreal.DccMcpEditorWindowLibrary.get_main_frame_identity_json()` returns a JSON
string with schema `dcc-unreal-editor-main-frame/v1`. It takes no caller target.
This is a bootstrap identity getter, not observation or input authorization.

On success the exact fields are `schema`, `success: true`, `reason: "ok"`,
`host_pid`, `window_pid`, and `window_handle`. Both PIDs are positive uint32 JSON
numbers and match the actual current process. `window_handle` is a positive
canonical decimal **string**, avoiding HWND precision loss in JSON numbers.
The bootstrap consumer must strictly parse it to a positive pointer-width int,
check both PIDs against its current process, and separately bind the actual
project and the owner profile. This getter does not establish those policies.

Failures contain only `schema`, `success: false`, and a stable `reason`; they
never contain a usable handle or PID. Reasons are `not_game_thread`, `not_editor`,
`unsupported_platform`, `main_frame_unavailable`, `main_frame_recreating`,
`main_frame_window_unavailable`, `native_window_unavailable`,
`os_window_unavailable`, `invalid_window`, `window_pid_unavailable`,
`host_pid_unavailable`, `foreign_process_window`, or `window_changed`.

The implementation must run on the GameThread. On Windows Editor it obtains
only the already loaded MainFrame module, its parent SWindow, its native window,
and its OS handle. Win32 `IsWindow` and `GetWindowThreadProcessId` validate that
the handle belongs to the current process. It does not load a module, create or
enumerate windows, inspect foreground/title/content, activate, capture, or input.
Non-Windows/non-Editor calls fail explicitly. UE4 uses the common MainFrame APIs;
the UE5 recreation check is guarded. The plugin adds MainFrame to its existing
Slate/ApplicationCore/Json dependencies.

The result is point-in-time metadata; it does not promise handle lifetime or
prevent subsequent destruction/reuse. The composition consumer and final input
fence must revalidate identity when they use it. Provider/runtime/PID/HWND
attestation and fresh observation remain separate requirements before UI work.

Offline tests only inspect source contracts. Native compilation, UHT/Python
reflection, a real getter call, startup composition, and host/UI acceptance must
be recorded separately; none are established by those tests.
