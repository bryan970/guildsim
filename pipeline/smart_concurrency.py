from guild_runtime import runtime_root, usable_faction
"""Bound native simulator CPU use by foreground activity and measured load."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import time


class SystemLoad:
    def __init__(self):
        self.previous = None

    def sample(self):
        if os.name != 'nt':
            return {'cpu': 0, 'wow_foreground': False}
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        idle, system, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
        cpu = 50
        if kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user)):
            number = lambda v: (v.dwHighDateTime << 32) | v.dwLowDateTime
            current = (number(idle), number(system) + number(user))
            if self.previous and current[1] > self.previous[1]:
                cpu = 100 * (1 - (current[0] - self.previous[0]) / (current[1] - self.previous[1]))
            self.previous = current
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        foreground = ''
        if handle:
            try:
                kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
                buffer = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(buffer))
                if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    foreground = Path(buffer.value).name.lower()
            finally:
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]; kernel.CloseHandle(handle)
        return {'cpu': max(0, min(100, cpu)), 'wow_foreground': foreground.startswith('wow') and foreground.endswith('.exe')}


def budget(sample, previous=4, logical_cpus=None):
    maximum = min(12, max(1, (logical_cpus or os.cpu_count() or 4) // 2))
    if sample['wow_foreground'] or sample['cpu'] >= 85:
        return min(4, maximum)
    # Increase gradually; measured load includes the simulator itself.
    if sample['cpu'] < 65:
        return min(maximum, previous + 4)
    return min(maximum, previous)


class Controller:
    def __init__(self):
        self.load = SystemLoad(); self.workers = min(4, os.cpu_count() or 4)
        self.last = 0; self.sample = {'cpu': 50, 'wow_foreground': False}

    def refresh(self):
        if time.monotonic() - self.last >= 1:
            try:
                self.sample = self.load.sample()
                self.workers = budget(self.sample, self.workers)
            except (OSError, ValueError):
                self.workers = min(4, os.cpu_count() or 4)
            self.last = time.monotonic()
        return self.workers

    def constrain(self, process):
        if os.name != 'nt':
            return
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        allowed, system = ctypes.c_size_t(), ctypes.c_size_t()
        # Respect an existing affinity restriction on the helper.
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        if not kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ctypes.byref(allowed), ctypes.byref(system)):
            return
        bits = [i for i in range(allowed.value.bit_length()) if allowed.value & (1 << i)]
        mask = sum(1 << bit for bit in bits[-self.workers:])
        kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        kernel.SetProcessAffinityMask(int(process._handle), mask)

    def status(self, processes):
        return {'cpuBudget': self.workers, 'activeProcesses': processes,
                'systemCpuPercent': round(self.sample['cpu']), 'wowForeground': self.sample['wow_foreground']}
