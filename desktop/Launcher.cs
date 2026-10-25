// Dolphin City Builder: the desktop app.
//
// The game itself runs on the server (PythonAnywhere), so everyone who has
// this app plays in the same world as the website. This program only opens
// the game in a window of its own: it starts Microsoft Edge or Google Chrome
// in "app mode" (no tabs, no address bar), with a profile kept just for the
// game so the player stays signed in. If neither browser is installed, the
// game opens in the normal default browser instead.
//
// Built with the C# compiler that comes with Windows: see build.bat.

using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

static class Launcher
{
    const string GameUrl = "https://dolphincitybuilder.duckdns.org/";
    const string AppName = "DolphinCityBuilder";

    [STAThread]
    static int Main(string[] args)
    {
        string url = GameUrl;
        bool dryRun = false;
        foreach (string a in args)
        {
            if (a.StartsWith("--url=")) url = a.Substring(6);     // for testing against another copy of the game
            else if (a == "--dry-run") dryRun = true;             // write what would be run to %TEMP% instead of running it
        }

        string browser = FindBrowser();
        string profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), AppName, "browser");
        string arguments = "--app=\"" + url + "\" --user-data-dir=\"" + profile + "\" --window-size=1280,860 " +
                           "--no-first-run --no-default-browser-check --disable-features=Translate";

        if (dryRun)
        {
            File.WriteAllText(Path.Combine(Path.GetTempPath(), "dcb_launch.txt"),
                              (browser ?? "(default browser)") + Environment.NewLine + (browser != null ? arguments : url));
            return 0;
        }
        try
        {
            if (browser != null)
            {
                Directory.CreateDirectory(profile);
                Process.Start(new ProcessStartInfo(browser, arguments) { UseShellExecute = false });
            }
            else
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            return 0;
        }
        catch (Exception e)
        {
            MessageBox.Show("Dolphin City Builder could not start.\n\n" + e.Message +
                            "\n\nYou can still play in any web browser at:\n" + url,
                            "Dolphin City Builder", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        }
    }

    // Edge first (every Windows 10 and 11 computer normally has it), then Chrome, then Brave.
    static string FindBrowser()
    {
        string[] exes = { "msedge.exe", "chrome.exe", "brave.exe" };
        string[] folders = {
            @"Microsoft\Edge\Application", @"Google\Chrome\Application", @"BraveSoftware\Brave-Browser\Application" };
        string[] roots = {
            Environment.GetEnvironmentVariable("ProgramFiles(x86)"),
            Environment.GetEnvironmentVariable("ProgramFiles"),
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) };
        for (int i = 0; i < exes.Length; i++)
        {
            foreach (RegistryKey hive in new[] { Registry.CurrentUser, Registry.LocalMachine })
            {
                using (RegistryKey key = hive.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\" + exes[i]))
                {
                    string path = key == null ? null : key.GetValue("") as string;
                    if (!string.IsNullOrEmpty(path) && File.Exists(path.Trim('"'))) return path.Trim('"');
                }
            }
            foreach (string root in roots)
            {
                if (string.IsNullOrEmpty(root)) continue;
                string path = Path.Combine(root, folders[i], exes[i]);
                if (File.Exists(path)) return path;
            }
        }
        return null;
    }
}
