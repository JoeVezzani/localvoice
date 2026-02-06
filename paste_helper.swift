// paste_helper - simulates Cmd+V to paste clipboard contents
// Compile: swiftc paste_helper.swift -o paste_helper -framework Cocoa -framework ApplicationServices
import Cocoa
import CoreGraphics
import ApplicationServices

let trusted = AXIsProcessTrusted()
fputs("AXIsProcessTrusted: \(trusted)\n", stderr)

if !trusted {
    fputs("ERROR: No Accessibility permission.\n", stderr)
    fputs("Add paste_helper to: System Settings > Privacy & Security > Accessibility\n", stderr)
    exit(1)
}

let src = CGEventSource(stateID: .hidSystemState)
let cmdDown = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: true)!  // 9 = 'v'
cmdDown.flags = .maskCommand
let cmdUp = CGEvent(keyboardEventSource: src, virtualKey: 9, keyDown: false)!
cmdUp.flags = .maskCommand
cmdDown.post(tap: .cghidEventTap)
usleep(20000)  // 20ms between down and up
cmdUp.post(tap: .cghidEventTap)
fputs("Cmd+V posted\n", stderr)
