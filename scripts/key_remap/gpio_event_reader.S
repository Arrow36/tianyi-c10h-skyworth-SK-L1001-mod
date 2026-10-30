// ARM EABI, no libc. Read one input_event at a time from argv[1].
// Emit four hex words (seconds, microseconds, code/type, value), immediately.
// It only reads the input device; all key behavior stays in toggle.sh.
.arm
    ldr r1, [sp]
    cmp r1, #2
    blo error_exit
    ldr r0, [sp, #8]
    mov r1, #0
    mov r7, #5
    svc #0
    cmp r0, #0
    blt error_exit
    mov r8, r0
    sub sp, sp, #96
read_event:
    mov r0, r8
    mov r1, sp
    mov r2, #16
    mov r7, #3
    svc #0
    cmp r0, #0
    ble clean_exit
    cmp r0, #16
    bne read_event
    mov r4, sp
    add r5, sp, #32
    mov r6, #4
next_word:
    ldr r0, [r4], #4
    mov r1, #28
next_nibble:
    mov r2, r0, lsr r1
    and r2, r2, #15
    cmp r2, #10
    addlo r2, r2, #48
    addhs r2, r2, #87
    strb r2, [r5], #1
    subs r1, r1, #4
    bpl next_nibble
    subs r6, r6, #1
    moveq r2, #10
    movne r2, #32
    strb r2, [r5], #1
    bne next_word
    mov r0, #1
    add r1, sp, #32
    mov r2, #36
    mov r7, #4
    svc #0
    b read_event
clean_exit:
    mov r0, #0
    mov r7, #1
    svc #0
error_exit:
    mov r0, #2
    mov r7, #1
    svc #0
