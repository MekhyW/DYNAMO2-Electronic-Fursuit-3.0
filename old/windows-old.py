import psutil
import os
import subprocess
import json
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
import comtypes
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

input_audio_devices = []
output_audio_devices = []
default_input_device = None
default_output_device = None

def get_cpu_info():
    return {
        "physical_cores": psutil.cpu_count(logical=False),
        "total_cores": psutil.cpu_count(logical=True),
        "max_frequency": psutil.cpu_freq().max,
        "min_frequency": psutil.cpu_freq().min,
        "current_frequency": psutil.cpu_freq().current,
        "usage": psutil.cpu_percent(interval=1)
    }

def get_memory_info():
    virtual_memory = psutil.virtual_memory()
    return {
        "total": virtual_memory.total,
        "available": virtual_memory.available,
        "used": virtual_memory.used,
        "percent": virtual_memory.percent
    }

def get_disk_info():
    disk_usage = psutil.disk_usage('/')
    return {
        "total": disk_usage.total,
        "used": disk_usage.used,
        "free": disk_usage.free,
        "percent": disk_usage.percent
    }

def get_system_volume():
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    return volume.GetMasterVolumeLevelScalar()

def set_system_volume(volume_level):
    comtypes.CoInitialize()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(
        IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(volume_level, None)

def shutdown():
    os.system("shutdown /s /t 1")

def restart():
    os.system("shutdown /r /t 1")

def kill_process(process_name):
    os.system("taskkill /f /im " + process_name)

def refresh_sound_devices():
    global input_audio_devices, output_audio_devices, default_input_device, default_output_device
    subprocess.call(["SoundVolumeView.exe", "/sjson", "sound_volume.json"], shell=True)
    with open("sound_volume.json", "rb") as f:
        audiodevices = json.load(f)
    input_audio_devices = []
    output_audio_devices = []
    for audiodevice in audiodevices:
        if audiodevice["Type"] != "Device":
            continue
        if audiodevice["Default"] == "Capture":
            default_input_device = audiodevice["Item ID"]
        elif audiodevice["Default"] == "Render":
            default_output_device = audiodevice["Item ID"]
        if audiodevice["Direction"] == "Capture":
            input_audio_devices.append({'Name': audiodevice["Device Name"][:30], 'ID': audiodevice["Item ID"]})
        else:
            output_audio_devices.append({'Name': audiodevice["Device Name"][:30], 'ID': audiodevice["Item ID"]})

def set_default_sound_device(device_name, direction):
    def find_device_id(devices, name, direction):
        global default_input_device, default_output_device
        for device in devices:
            if device['Name'] == name:
                if direction == "input":
                    default_input_device = device["ID"]
                elif direction == "output":
                    default_output_device = device["ID"]
                return device['ID']
        return None
    if direction == "input":
        device_id = find_device_id(input_audio_devices, device_name, "input")
    elif direction == "output":
        device_id = find_device_id(output_audio_devices, device_name, "output")
    if device_id is None:
        raise ValueError(f"Device '{device_name}' not found in input or output devices.")
    subprocess.call(["SoundVolumeView.exe", "/SetDefault", device_id, "all"], shell=True)

def mute_microphone():
    if default_input_device is None:
        refresh_sound_devices()
    subprocess.call(["SoundVolumeView.exe", "/Mute", default_input_device], shell=True)

def unmute_microphone():
    if default_input_device is None:
        refresh_sound_devices()
    subprocess.call(["SoundVolumeView.exe", "/Unmute", default_input_device], shell=True)

if __name__ == "__main__":
    cpu_info = get_cpu_info()
    memory_info = get_memory_info()
    disk_info = get_disk_info()
    system_volume = get_system_volume()
    print(f"CPU Usage: {cpu_info['usage']}%")
    print(f"Memory Usage: {memory_info['percent']}%")
    print(f"Disk Usage: {disk_info['percent']}%")
    print(f"System Volume: {system_volume * 100:.2f}%")
    #set_system_volume(0.5)
    #print('Rebooting in 5 seconds...')
    #import time
    #time.sleep(5)
    #restart()
    #kill_process("chrome.exe")
    refresh_sound_devices()
    print(input_audio_devices, output_audio_devices)