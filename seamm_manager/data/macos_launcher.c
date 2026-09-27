/*
 * Launcher for the SEAMM app bundles on macOS.
 *
 * macOS needs an app bundle's executable to be a compiled (Mach-O) program: a
 * shell script carries no architecture, so on Apple Silicon without Rosetta the
 * system asks the user to install Rosetta before it will launch the app. This
 * universal (arm64 + x86_64) program is copied in as Contents/MacOS/<name>; it
 * runs the bundle's Contents/Resources/<name>.sh with /bin/bash, passing on
 * any arguments, so the command itself stays an editable text file.
 *
 * Rebuild with `make launcher` in the seamm_manager checkout (needs Xcode's
 * command line tools); the binary is committed so users need no compiler.
 */
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    char raw[PATH_MAX];
    uint32_t size = sizeof(raw);
    if (_NSGetExecutablePath(raw, &size) != 0) {
        fprintf(stderr, "SEAMM launcher: executable path too long\n");
        return 127;
    }
    char exe[PATH_MAX];
    if (realpath(raw, exe) == NULL) {
        perror("SEAMM launcher: realpath");
        return 127;
    }

    /* <bundle>/Contents/MacOS/<name>  ->  <bundle>/Contents/Resources/<name>.sh */
    char exe_copy[PATH_MAX], dir_copy[PATH_MAX];
    strncpy(exe_copy, exe, sizeof(exe_copy));
    strncpy(dir_copy, exe, sizeof(dir_copy));
    const char *name = basename(exe_copy);
    const char *macos_dir = dirname(dir_copy);

    char script[PATH_MAX];
    int n = snprintf(script, sizeof(script), "%s/../Resources/%s.sh", macos_dir, name);
    if (n < 0 || n >= (int)sizeof(script)) {
        fprintf(stderr, "SEAMM launcher: script path too long\n");
        return 127;
    }

    char **args = calloc((size_t)argc + 2, sizeof(char *));
    if (args == NULL) {
        perror("SEAMM launcher: calloc");
        return 127;
    }
    args[0] = "/bin/bash";
    args[1] = script;
    for (int i = 1; i < argc; i++) {
        args[i + 1] = argv[i];
    }
    args[argc + 1] = NULL;

    execv("/bin/bash", args);
    perror("SEAMM launcher: could not run /bin/bash");
    return 127;
}
