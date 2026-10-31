// uinput_injector.c - Zero-libc micro-daemon for instant Android key injection
// Registers a kernel uinput device once at boot and executes key events in < 0.1ms.
// Compile: arm-none-eabi-gcc -nostdlib -fno-builtin -march=armv7-a -O2 -Wl,-e,_start -Wl,-Ttext=0x10000 -Wl,-z,max-page-size=4096 -o uinput_injector uinput_injector.c

#define O_RDONLY    00
#define O_WRONLY    01
#define O_RDWR      02
#define O_NONBLOCK  04000

#define EV_SYN      0x00
#define SYN_REPORT  0x00
#define EV_KEY      0x01

#define KEY_ENTER   28
#define KEY_POWER   116
#define KEY_SLEEP   142
#define KEY_WAKEUP  143
#define KEY_BACK    158

#define UI_SET_EVBIT    0x40045564
#define UI_SET_KEYBIT   0x40045565
#define UI_DEV_CREATE   0x5501
#define UI_DEV_DESTROY  0x5502

struct input_event {
    long tv_sec;
    long tv_usec;
    unsigned short type;
    unsigned short code;
    int value;
};

struct input_id {
    unsigned short bustype;
    unsigned short vendor;
    unsigned short product;
    unsigned short version;
};

struct uinput_user_dev {
    char name[80];
    struct input_id id;
    unsigned int ff_effects_max;
    int absmax[64];
    int absmin[64];
    int absfuzz[64];
    int absflat[64];
};

struct timespec {
    long tv_sec;
    long tv_nsec;
};

static int g_ufd = -1;

static inline int sys_open(const char *path, int flags, int mode) {
    register int r0 asm("r0") = (int)path;
    register int r1 asm("r1") = flags;
    register int r2 asm("r2") = mode;
    register int r7 asm("r7") = 5; // sys_open
    asm volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_close(int fd) {
    register int r0 asm("r0") = fd;
    register int r7 asm("r7") = 6; // sys_close
    asm volatile("svc #0" : "+r"(r0) : "r"(r7) : "memory");
    return r0;
}

static inline int sys_read(int fd, void *buf, int count) {
    register int r0 asm("r0") = fd;
    register int r1 asm("r1") = (int)buf;
    register int r2 asm("r2") = count;
    register int r7 asm("r7") = 3; // sys_read
    asm volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 asm("r0") = fd;
    register int r1 asm("r1") = (int)buf;
    register int r2 asm("r2") = count;
    register int r7 asm("r7") = 4; // sys_write
    asm volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_ioctl(int fd, unsigned int cmd, unsigned long arg) {
    register int r0 asm("r0") = fd;
    register int r1 asm("r1") = (int)cmd;
    register int r2 asm("r2") = (int)arg;
    register int r7 asm("r7") = 54; // sys_ioctl
    asm volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_nanosleep(const struct timespec *req, struct timespec *rem) {
    register int r0 asm("r0") = (int)req;
    register int r1 asm("r1") = (int)rem;
    register int r7 asm("r7") = 162; // sys_nanosleep
    asm volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory");
    return r0;
}

static inline void sys_exit(int code) {
    if (g_ufd >= 0) {
        sys_ioctl(g_ufd, UI_DEV_DESTROY, 0);
        sys_close(g_ufd);
        g_ufd = -1;
    }
    register int r0 asm("r0") = code;
    register int r7 asm("r7") = 1; // sys_exit
    asm volatile("svc #0" : : "r"(r0), "r"(r7));
    while (1);
}

static void emit_key(int uinput_fd, unsigned short code) {
    struct input_event ev[4];
    // Key Down
    ev[0].tv_sec = 0; ev[0].tv_usec = 0;
    ev[0].type = EV_KEY; ev[0].code = code; ev[0].value = 1;
    // Syn
    ev[1].tv_sec = 0; ev[1].tv_usec = 0;
    ev[1].type = EV_SYN; ev[1].code = SYN_REPORT; ev[1].value = 0;
    // Key Up
    ev[2].tv_sec = 0; ev[2].tv_usec = 0;
    ev[2].type = EV_KEY; ev[2].code = code; ev[2].value = 0;
    // Syn
    ev[3].tv_sec = 0; ev[3].tv_usec = 0;
    ev[3].type = EV_SYN; ev[3].code = SYN_REPORT; ev[3].value = 0;

    sys_write(uinput_fd, ev, sizeof(ev));
}

void *memset(void *s, int c, unsigned int n) {
    unsigned char *p = (unsigned char *)s;
    for (unsigned int i = 0; i < n; i++) {
        p[i] = (unsigned char)c;
    }
    return s;
}

__attribute__((noreturn)) void _start(void) {
    const char uinput_path[] = "/dev/uinput";
    g_ufd = sys_open(uinput_path, O_WRONLY | O_NONBLOCK, 0);
    if (g_ufd < 0) {
        sys_exit(1);
    }

    // Configure supported events
    sys_ioctl(g_ufd, UI_SET_EVBIT, EV_KEY);
    sys_ioctl(g_ufd, UI_SET_KEYBIT, KEY_BACK);
    sys_ioctl(g_ufd, UI_SET_KEYBIT, KEY_ENTER);
    sys_ioctl(g_ufd, UI_SET_KEYBIT, KEY_SLEEP);
    sys_ioctl(g_ufd, UI_SET_KEYBIT, KEY_WAKEUP);
    sys_ioctl(g_ufd, UI_SET_KEYBIT, KEY_POWER);

    // Setup virtual device
    struct uinput_user_dev dev;
    char *p = (char *)&dev;
    for (int i = 0; i < (int)sizeof(dev); i++) p[i] = 0;

    const char dev_name[] = "c10h_keys";
    for (int i = 0; dev_name[i]; i++) dev.name[i] = dev_name[i];
    dev.id.bustype = 0x06; // BUS_VIRTUAL
    dev.id.vendor = 0x1234;
    dev.id.product = 0x5678;
    dev.id.version = 1;

    sys_write(g_ufd, &dev, sizeof(dev));
    sys_ioctl(g_ufd, UI_DEV_CREATE, 0);

    // Open FIFO with O_RDWR to prevent EOF when writers disconnect
    const char fifo_path[] = "/data/local/codex-screen-toggle/run/key.fifo";
    int fifo_fd = -1;
    struct timespec retry_ts = {0, 100000000}; // 100ms

    while (fifo_fd < 0) {
        fifo_fd = sys_open(fifo_path, O_RDWR, 0);
        if (fifo_fd < 0) {
            sys_nanosleep(&retry_ts, 0);
        }
    }

    char buf[16];
    while (1) {
        int n = sys_read(fifo_fd, buf, sizeof(buf));
        if (n <= 0) {
            sys_nanosleep(&retry_ts, 0);
            continue;
        }
        for (int i = 0; i < n; i++) {
            char c = buf[i];
            if (c == 'B' || c == '4') {
                emit_key(g_ufd, KEY_BACK);
            } else if (c == 'C' || c == '2') {
                emit_key(g_ufd, KEY_ENTER);
            } else if (c == 'S') {
                emit_key(g_ufd, KEY_SLEEP);
            } else if (c == 'W') {
                emit_key(g_ufd, KEY_WAKEUP);
            } else if (c == 'P') {
                emit_key(g_ufd, KEY_POWER);
            }
        }
    }
}
