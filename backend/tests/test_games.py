from games import GameDetector, friendly_name

DEADLOCK = r"D:\SteamLibrary\steamapps\common\Deadlock\game\bin\win64\project8.exe"


class P:
    def __init__(self, pid, name, exe):
        self.info = {"pid": pid, "name": name, "exe": exe}


def procs(*items):
    return lambda attrs: [P(i, n, e) for i, (n, e) in enumerate(items, 1)]


DESKTOP = [
    ("explorer.exe", r"C:\Windows\explorer.exe"),
    ("chrome.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    ("Discord.exe", r"C:\Users\x\AppData\Local\Discord\app-1.0\Discord.exe"),
    ("steam.exe", r"C:\Program Files (x86)\Steam\steam.exe"),
    ("steamwebhelper.exe", r"C:\Program Files (x86)\Steam\bin\cef\steamwebhelper.exe"),
    ("wallpaper64.exe", r"C:\Program Files (x86)\Steam\steamapps\common\wallpaper_engine\wallpaper64.exe"),
    ("EpicGamesLauncher.exe", r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"),
    ("RiotClientServices.exe", r"C:\Riot Games\Riot Client\RiotClientServices.exe"),
    ("System", ""),
]


def test_friendly_names():
    assert friendly_name(DEADLOCK, "project8.exe") == "Deadlock"
    assert friendly_name(r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient.exe",
                         "FortniteClient.exe") == "Fortnite"
    assert friendly_name(r"C:\Games\osu!\osu!.exe", "osu!.exe") == "osu!"


def test_desktop_and_launchers_are_not_games():
    d = GameDetector(process_iter=procs(*DESKTOP))
    assert d.scan() is None


def test_deadlock_detected():
    d = GameDetector(process_iter=procs(*DESKTOP, ("project8.exe", DEADLOCK)))
    g = d.scan()
    assert g.name == "Deadlock" and g.exe == "project8.exe" and str(g) == "Deadlock (project8.exe)"


def test_other_stores_detected():
    for name, path in [
        ("VALORANT-Win64-Shipping.exe", r"C:\Riot Games\VALORANT\live\ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe"),
        ("FortniteClient-Win64-Shipping.exe", r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe"),
        ("Forza.exe", r"C:\XboxGames\Forza Horizon 5\Content\ForzaHorizon5.exe"),
    ]:
        assert GameDetector(process_iter=procs((name, path))).scan() is not None, name


def test_custom_games_and_ignore_list():
    mc = ("javaw.exe", r"C:\Program Files\Java\bin\javaw.exe")
    assert GameDetector(process_iter=procs(mc)).scan() is None
    assert GameDetector("javaw.exe, osu!", process_iter=procs(mc)).scan().exe == "javaw.exe"
    assert GameDetector("osu!", process_iter=procs(("osu!.exe", r"C:\Games\osu!\osu!.exe"))).scan()
    tool = ("mytool.exe", r"D:\SteamLibrary\steamapps\common\SomeTool\mytool.exe")
    assert GameDetector(process_iter=procs(tool)).scan() is not None
    assert GameDetector(ignore="mytool.exe", process_iter=procs(tool)).scan() is None


def test_access_denied_processes_are_skipped():
    import psutil

    class Denied:
        @property
        def info(self):
            raise psutil.AccessDenied()
    d = GameDetector(process_iter=lambda attrs: [Denied(), P(9, "project8.exe", DEADLOCK)])
    assert d.scan().name == "Deadlock"


def test_launcher_background_services_are_not_games():
    """Found on the real PC: Epic Online Services runs all the time and was treated as a game."""
    services = [
        ("EpicOnlineServices.exe", r"C:\Program Files (x86)\Epic Games\Epic Online Services\EpicOnlineServices.exe"),
        ("EpicOnlineServicesHost.exe", r"C:\Program Files (x86)\Epic Games\Epic Online Services\service\EpicOnlineServicesHost.exe"),
        ("EOSOverlayRenderer-Win64-Shipping.exe", r"C:\Program Files (x86)\Epic Games\Epic Online Services\managedArtifacts\x\EOSOverlayRenderer-Win64-Shipping.exe"),
        ("UnrealCEFSubProcess.exe", r"C:\Program Files (x86)\Epic Games\Launcher\Engine\Binaries\Win64\UnrealCEFSubProcess.exe"),
        ("SomeNewHelper.exe", r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win64\SomeNewHelper.exe"),
        ("EACefSubProcess.exe", r"C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\EACefSubProcess.exe"),
        ("RiotClientElectron.exe", r"C:\Riot Games\Riot Client\UX\RiotClientElectron.exe"),
        ("vrstartup.exe", r"C:\Program Files (x86)\Steam\steamapps\common\SteamVR\bin\win64\vrstartup.exe"),
    ]
    d = GameDetector(process_iter=procs(*DESKTOP, *services))
    assert d.scan() is None
    # ...but real games from the same stores are still detected
    fortnite = ("FortniteClient-Win64-Shipping.exe",
                r"C:\Program Files\Epic Games\Fortnite\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe")
    assert GameDetector(process_iter=procs(*services, fortnite)).scan().name == "Fortnite"
