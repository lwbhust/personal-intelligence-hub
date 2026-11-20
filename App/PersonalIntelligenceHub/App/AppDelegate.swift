import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = SidecarViewModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Log.app.info("Personal Intelligence Hub launched")
    }

    func applicationWillTerminate(_ notification: Notification) {
        model.shutdownSynchronously()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
