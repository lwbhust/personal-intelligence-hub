import SwiftUI

@main
struct PersonalIntelligenceHubApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        Window("Personal Intelligence Hub", id: "main") {
            RootView(model: appDelegate.model)
        }
        .defaultSize(width: 1240, height: 820)
        .windowResizability(.contentMinSize)
    }
}
