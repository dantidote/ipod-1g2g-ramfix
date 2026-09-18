// Single-file distribution wrapper for the existing one-folder Python app.
// Elevates before extraction, then gives every extracted object an explicit
// Administrators/SYSTEM-only ACL and Administrators ownership. A filtered UAC
// token must not be able to replace a DLL that the elevated app will load.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Windows.Forms;

internal static class WindowsLauncher
{
    private const string PayloadHash = "@PAYLOAD_SHA256@";
    private static readonly SecurityIdentifier Admins = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
    private static readonly SecurityIdentifier SystemAccount = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);

    private static bool IsAdmin()
    {
        using (WindowsIdentity id = WindowsIdentity.GetCurrent())
            return new WindowsPrincipal(id).IsInRole(WindowsBuiltInRole.Administrator);
    }

    private static bool OfflineArguments(string[] args)
    {
        return args.Length == 3 && (args[0] == "--self-test" || args[0] == "--ui-smoke-test")
            && args[1] == "--result" && !String.IsNullOrWhiteSpace(args[2]);
    }

    private static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            result.Append('\\', slashes * (c == '"' ? 2 : 1));
            slashes = 0;
            if (c == '"') result.Append('\\');
            result.Append(c);
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    private static FileSystemSecurity Security(bool directory, bool elevated)
    {
        FileSystemSecurity security = directory ? (FileSystemSecurity)new DirectorySecurity() : new FileSecurity();
        security.SetAccessRuleProtection(true, false);
        SecurityIdentifier owner;
        using (WindowsIdentity id = WindowsIdentity.GetCurrent()) owner = elevated ? Admins : id.User;
        security.SetOwner(owner);
        var inheritance = directory ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit : InheritanceFlags.None;
        security.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
            inheritance, PropagationFlags.None, AccessControlType.Allow));
        security.AddAccessRule(new FileSystemAccessRule(SystemAccount, FileSystemRights.FullControl,
            inheritance, PropagationFlags.None, AccessControlType.Allow));
        return security;
    }

    private static void CheckSecurity(string path, bool directory, bool elevated)
    {
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("An unexpected link was found in the temporary app folder.");
        FileSystemSecurity security = directory ? (FileSystemSecurity)Directory.GetAccessControl(path)
                                                : File.GetAccessControl(path);
        SecurityIdentifier owner;
        using (WindowsIdentity id = WindowsIdentity.GetCurrent()) owner = elevated ? Admins : id.User;
        if (!security.GetOwner(typeof(SecurityIdentifier)).Equals(owner) || !security.AreAccessRulesProtected)
            throw new IOException("The temporary app folder could not be secured.");
        foreach (FileSystemAccessRule rule in security.GetAccessRules(true, true, typeof(SecurityIdentifier)))
            if (rule.AccessControlType != AccessControlType.Allow ||
                (!rule.IdentityReference.Equals(owner) && !rule.IdentityReference.Equals(SystemAccount)))
                throw new IOException("Unexpected permissions on extracted app files.");
    }

    private static string Inside(string root, string name)
    {
        string destination = Path.GetFullPath(Path.Combine(root, name));
        if (!destination.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new IOException("Invalid path in the embedded application.");
        return destination;
    }

    private static void MakeDirectories(string root, string path, bool elevated)
    {
        if (path == root) return;
        Inside(root, path);
        MakeDirectories(root, Path.GetDirectoryName(path), elevated);
        if (!Directory.Exists(path))
            Directory.CreateDirectory(path, (DirectorySecurity)Security(true, elevated));
        CheckSecurity(path, true, elevated);
    }

    private static void Extract(string root, bool elevated)
    {
        using (Stream data = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.zip"))
        {
            if (data == null) throw new IOException("The embedded application is missing.");
            using (SHA256 hash = SHA256.Create())
                if (BitConverter.ToString(hash.ComputeHash(data)).Replace("-", "").ToLowerInvariant() != PayloadHash)
                    throw new IOException("The download is damaged. Download the app again.");
            data.Position = 0;
            using (ZipArchive archive = new ZipArchive(data, ZipArchiveMode.Read))
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string path = Inside(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                    if (entry.FullName.EndsWith("/"))
                    {
                        MakeDirectories(root, path.TrimEnd(Path.DirectorySeparatorChar), elevated);
                        continue;
                    }
                    MakeDirectories(root, Path.GetDirectoryName(path), elevated);
                    using (Stream input = entry.Open())
                    using (FileStream output = new FileStream(path, FileMode.CreateNew, FileSystemRights.Write,
                        FileShare.None, 81920, FileOptions.None, (FileSecurity)Security(false, elevated)))
                        input.CopyTo(output);
                    CheckSecurity(path, false, elevated);
                }
        }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        bool offline = OfflineArguments(args);
        bool elevated = IsAdmin();
        string root = null;
        string parent = null;
        string failure = null;
        bool created = false;
        int exitCode = 1;
        try
        {
            if (offline) args[2] = Path.GetFullPath(args[2]);
            if (!elevated && !offline)
            {
                var restart = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
                    String.Join(" ", args.Select(Quote))) {
                    UseShellExecute = true, Verb = "runas", WorkingDirectory = Environment.SystemDirectory };
                using (Process child = Process.Start(restart)) { child.WaitForExit(); return child.ExitCode; }
            }
            parent = Path.GetFullPath(elevated ? Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles)
                                               : Path.GetTempPath()).TrimEnd(Path.DirectorySeparatorChar);
            root = Inside(parent, "iPod-RAM-Fix-session-" + Guid.NewGuid().ToString("N"));
            if (Directory.Exists(root) || File.Exists(root)) throw new IOException("Temporary folder already exists.");
            Directory.CreateDirectory(root, (DirectorySecurity)Security(true, elevated));
            created = true;
            CheckSecurity(root, true, elevated);
            Extract(root, elevated);
            string executable = Inside(root, "app\\iPod-RAM-Fix.exe");
            var launch = new ProcessStartInfo(executable, String.Join(" ", args.Select(Quote))) {
                UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(executable) };
            launch.EnvironmentVariables["IPOD_RAMFIX_SESSION_DIR"] = root;
            using (Process child = Process.Start(launch)) { child.WaitForExit(); exitCode = child.ExitCode; }
        }
        catch (Exception error)
        {
            failure = error.ToString();
            if (!offline) MessageBox.Show(error.Message, "iPod RAM Fix", MessageBoxButtons.OK, MessageBoxIcon.Error);
            exitCode = 1;
        }
        finally
        {
            // Only remove the unique directory created by this process. Its
            // bounds and ACL are checked again before any recursive deletion.
            if (created && root != null && Directory.Exists(root))
            {
                try
                {
                    Inside(parent, root);
                    if (!Path.GetFileName(root).StartsWith("iPod-RAM-Fix-session-", StringComparison.Ordinal))
                        throw new IOException("Invalid cleanup path");
                    CheckSecurity(root, true, elevated);
                    Directory.Delete(root, true);
                }
                catch (Exception error) { if (offline) { failure = error.ToString(); exitCode = 1; } }
            }
        }
        if (offline && exitCode == 0)
        {
            string report = "{\"launcher\":\"passed\",\"elevated\":" + (elevated ? "true" : "false")
                + ",\"payload_hash_verified\":true,\"extracted_acl_verified\":true,\"temporary_folder_removed\":"
                + (!Directory.Exists(root) ? "true" : "false") + "}";
            using (var stream = new FileStream(args[2] + ".launcher.json", FileMode.CreateNew, FileAccess.Write))
            using (var writer = new StreamWriter(stream)) writer.Write(report);
        }
        else if (offline)
        {
            using (var stream = new FileStream(args[2] + ".launcher-error.txt", FileMode.CreateNew, FileAccess.Write))
            using (var writer = new StreamWriter(stream)) writer.Write(failure ?? "The embedded app's check failed.");
        }
        return exitCode;
    }
}
