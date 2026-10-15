/* Compatibility shim for a read-only root file system (LD_PRELOAD, used by the adapter only).
 *
 * ITS-Tools tries to chmod +x its bundled binaries each time it runs and fails when it cannot,
 * although they are already executable (the image sets that at build time). Under the container
 * profile of this platform the root is read-only, so chmod answers EROFS. This shim answers
 * success for a file under /opt/tool that is already executable, and passes every other call to
 * the real chmod, so it hides nothing else.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define PREFIX "/opt/tool/"

static int already_executable(const char *path) {
    return path != NULL && strncmp(path, PREFIX, strlen(PREFIX)) == 0 && access(path, X_OK) == 0;
}

int chmod(const char *path, mode_t mode) {
    static int (*real)(const char *, mode_t);
    if (already_executable(path) && (mode & S_IXUSR)) {
        return 0;
    }
    if (!real) {
        real = (int (*)(const char *, mode_t))dlsym(RTLD_NEXT, "chmod");
    }
    return real(path, mode);
}

int fchmodat(int dirfd, const char *path, mode_t mode, int flags) {
    static int (*real)(int, const char *, mode_t, int);
    if (dirfd == AT_FDCWD && already_executable(path) && (mode & S_IXUSR)) {
        return 0;
    }
    if (!real) {
        real = (int (*)(int, const char *, mode_t, int))dlsym(RTLD_NEXT, "fchmodat");
    }
    return real(dirfd, path, mode, flags);
}
