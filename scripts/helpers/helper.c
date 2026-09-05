/* MIT. Copyright (c) 2026 RDR2Mac contributors.
 * SocialClub behavior adapted from Matthias Schedel's 2026 MIT shim.
 * See THIRD_PARTY_NOTICES.md for the original license.
 */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

/* Stable engine-recognized identity; exported so linker optimization retains it. */
__declspec(dllexport) const char rdr2mac_helper_identity[] = "RDR2MAC_HELPER_SHIM";

#define CAP 32768
static wchar_t command[CAP];
static size_t used;
static BOOL append(wchar_t c) {
    if (used >= CAP - 1) return FALSE;
    command[used++] = c;
    command[used] = 0;
    return TRUE;
}
/* Microsoft CRT argument quoting: double backslashes before a quote and
 * before the closing quote. Every argument is quoted, including empty ones. */
static BOOL argument(const wchar_t *s) {
    if (used && !append(L' ')) return FALSE;
    if (!append(L'"')) return FALSE;
    while (*s) {
        size_t slashes = 0;
        while (*s == L'\\') { ++slashes; ++s; }
        size_t copies = (*s == L'"' || !*s) ? slashes * 2 : slashes;
        while (copies--) if (!append(L'\\')) return FALSE;
        if (!*s) break;
        if (*s == L'"' && !append(L'\\')) return FALSE;
        if (!append(*s++)) return FALSE;
    }
    return append(L'"');
}
int WINAPI wWinMain(HINSTANCE h, HINSTANCE previous, PWSTR raw, int show) {
    (void)h; (void)previous; (void)raw; (void)show;
    static wchar_t real[CAP];
#ifdef STEAM_HELPER
    const wchar_t *delegate = L"steamwebhelper_real.exe";
    const wchar_t *flags[] = { L"--no-sandbox", L"--in-process-gpu", L"--disable-gpu" };
#else
    const wchar_t *delegate = L"SocialClubHelper_real.exe";
    const wchar_t *flags[] = { L"--in-process-gpu", L"--use-gl=angle", L"--use-angle=swiftshader" };
#endif
    DWORD length = GetModuleFileNameW(NULL, real, CAP);
    if (!length || length >= CAP) return ERROR_INSUFFICIENT_BUFFER;
    wchar_t *base = wcsrchr(real, L'\\');
    if (!base) return ERROR_BAD_PATHNAME;
    ++base;
    if ((size_t)(base - real) + wcslen(delegate) >= CAP) return ERROR_INSUFFICIENT_BUFFER;
    wcscpy(base, delegate);
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return ERROR_NOT_ENOUGH_MEMORY;
    BOOL ok = argument(real);
    for (size_t i = 0; ok && i < sizeof flags / sizeof flags[0]; ++i) ok = argument(flags[i]);
    for (int i = 1; ok && i < argc; ++i) {
#ifndef STEAM_HELPER
        if (!wcscmp(argv[i], L"--use-gl=swiftshader")) continue;
#endif
        BOOL duplicate = FALSE;
        for (size_t j = 0; j < sizeof flags / sizeof flags[0]; ++j)
            if (!wcscmp(argv[i], flags[j])) duplicate = TRUE;
        if (!duplicate) ok = argument(argv[i]);
    }
    LocalFree(argv);
    if (!ok) return ERROR_INSUFFICIENT_BUFFER;
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof startup);
    ZeroMemory(&process, sizeof process);
    GetStartupInfoW(&startup);
    startup.cb = sizeof startup;
    /* CEF passes inheritable IPC handles through its arguments. */
    if (!CreateProcessW(real, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process))
        return (int)GetLastError();
    CloseHandle(process.hThread);
    if (WaitForSingleObject(process.hProcess, INFINITE) != WAIT_OBJECT_0) {
        DWORD error = GetLastError();
        CloseHandle(process.hProcess);
        return (int)error;
    }
    DWORD code;
    if (!GetExitCodeProcess(process.hProcess, &code)) code = GetLastError();
    CloseHandle(process.hProcess);
    return (int)code;
}
