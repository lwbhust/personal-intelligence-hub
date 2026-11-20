import SwiftUI

struct StatusView: View {
    @ObservedObject var model: SidecarViewModel
    @State private var stderrExpanded = true
    @State private var collectionStatus: CollectionStatusDTO?
    @State private var collectionStatusError: String?
    @State private var isLoadingCollectionStatus = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(PIHColor.hairline)
            ScrollView {
                VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                    statusCard
                    if model.apiClientForFeatures != nil {
                        collectionCard
                    }
                    if let warning = model.healthWarning {
                        noticeRow(
                            icon: "exclamationmark.triangle.fill",
                            tint: .orange,
                            title: "健康警告",
                            text: warning
                        )
                    }
                    if let error = model.errorMessage {
                        errorCard(error)
                    }
                    advancedSection
                    if model.state == .idle {
                        emptyHint
                    }
                }
                .padding(.horizontal, PIHSpacing.page)
                .padding(.vertical, PIHSpacing.section)
            }
        }
        .frame(minWidth: 660, minHeight: 540)
        .background(PIHColor.canvas)
        .onAppear { model.autoStartIfNeeded() }
        .task(id: model.state) { await loadCollectionStatus() }
    }

    // MARK: - Header

    private var header: some View {
        PIHPageToolbar {
            PageHeader("运行状态", subtitle: "本地 Sidecar 与采集引擎") {
                HStack(spacing: PIHSpacing.control) {
                    StatusPill(text: model.state.title, tint: model.state.tint)

                    Button("启动") { model.start() }
                        .keyboardShortcut("r", modifiers: .command)
                        .disabled(!model.canStart)
                        .accessibilityLabel("启动 Sidecar")

                    Button("停止") { model.stop() }
                        .keyboardShortcut(".", modifiers: .command)
                        .disabled(!model.canStop)
                        .accessibilityLabel("停止 Sidecar")

                    Button("立即检查") { model.checkNow() }
                        .keyboardShortcut("e", modifiers: .command)
                        .disabled(!model.canCheck)
                        .accessibilityLabel("立即执行一次健康检查")
                }
                .controlSize(.small)
            }
        }
    }

    // MARK: - Status

    private var statusCard: some View {
        HStack(alignment: .top, spacing: 16) {
            Circle()
                .fill(model.state.tint)
                .frame(width: 12, height: 12)
                .padding(.top, 8)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Text(model.state.title)
                        .font(PIHFont.sectionTitle)
                    if model.state == .starting || model.state == .stopping {
                        ProgressView().controlSize(.small)
                    }
                    if model.isChecking {
                        ProgressView().controlSize(.mini)
                        Text("健康检查中…")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(model.state.summary)
                    .font(PIHFont.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let detail = model.statusDetail {
                    Text(detail)
                        .font(PIHFont.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: 0)
        }
        .pihCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Sidecar 状态：\(model.state.title)")
    }

    // MARK: - Collection engine

    private var collectionCard: some View {
        PIHCard {
            HStack {
                Text("采集引擎")
                    .font(PIHFont.cardTitle)
                if isLoadingCollectionStatus {
                    ProgressView().controlSize(.mini)
                }
                Spacer()
                Button("刷新") {
                    Task { await loadCollectionStatus() }
                }
                .controlSize(.small)
                .disabled(isLoadingCollectionStatus)
            }
            if let status = collectionStatus {
                Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 9) {
                    GridRow {
                        label("定时调度")
                        value(status.schedulerEnabled ? "已启用" : "已禁用")
                    }
                    GridRow {
                        label("正在执行的任务")
                        value(status.runningJobId ?? "—")
                    }
                    GridRow {
                        label("单任务并发上限")
                        value("\(status.maxConcurrency)")
                    }
                    GridRow {
                        label("排队任务数")
                        value("\(status.queueDepth)")
                    }
                }
                .font(PIHFont.caption)
            } else if let error = collectionStatusError {
                Text("无法读取采集状态：\(error)")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            } else {
                Text("正在读取采集引擎状态…")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func loadCollectionStatus() async {
        guard let client = model.apiClientForFeatures else {
            collectionStatus = nil
            collectionStatusError = nil
            return
        }
        isLoadingCollectionStatus = true
        defer { isLoadingCollectionStatus = false }
        do {
            collectionStatus = try await client.fetchCollectionStatus()
            collectionStatusError = nil
        } catch {
            collectionStatus = nil
            collectionStatusError = (error as? APIRequestError)?.message ?? error.localizedDescription
        }
    }

    // MARK: - Advanced diagnostics

    private var advancedSection: some View {
        DisclosureGroup {
            VStack(alignment: .leading, spacing: PIHSpacing.cardGap) {
                detailsCard
                if !model.stderrTail.isEmpty {
                    stderrCard
                }
            }
            .padding(.top, 12)
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text("高级诊断")
                    .font(PIHFont.cardTitle)
                Text("进程、端口、数据库版本与 Sidecar 日志")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var detailsCard: some View {
        PIHCard {
            Text("运行信息")
                .font(PIHFont.cardTitle)
            Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 9) {
                GridRow {
                    label("Sidecar PID")
                    value(pidText)
                }
                GridRow {
                    label("端口")
                    value(model.port.map(String.init) ?? "—")
                }
                GridRow {
                    label("App 版本")
                    value(appVersionText)
                }
                GridRow {
                    label("后端版本")
                    value(model.backendVersion ?? model.handshakeVersion ?? "—")
                }
                GridRow {
                    label("契约期望版本")
                    value(PIHConstants.expectedServiceVersion)
                }
                GridRow {
                    label("Git Commit")
                    value(model.buildCommit ?? "未注入")
                }
                GridRow {
                    label("构建时间")
                    value(model.buildTime ?? "未注入")
                }
                GridRow {
                    label("数据库状态")
                    value(databaseText)
                }
                GridRow {
                    label("schema_version")
                    value(model.schemaVersion.map(String.init) ?? "—")
                }
                GridRow {
                    label("数据目录类型")
                    value(model.pathKind ?? "—")
                }
                GridRow {
                    label("后端运行时长")
                    value(uptimeText)
                }
                GridRow {
                    label("服务端时间 (UTC)")
                    value(model.serverTimestamp ?? "—")
                }
                GridRow {
                    label("最近一次健康检查（本地时间）")
                    value(timeText(model.lastCheckAt))
                }
                GridRow {
                    label("最近一次检查成功（本地时间）")
                    value(timeText(model.lastSuccessAt))
                }
                GridRow {
                    label("连续失败次数")
                    value("\(model.consecutiveFailures)")
                }
                if let requestID = model.requestID {
                    GridRow {
                        label("X-Request-ID")
                        value(requestID)
                    }
                }
            }
            .font(PIHFont.caption)
        }
    }

    private var appVersionText: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String
        guard let version else { return "—" }
        if let build { return "\(version) (\(build))" }
        return version
    }

    private func label(_ text: String) -> some View {        Text(text)
            .foregroundStyle(.secondary)
            .gridColumnAlignment(.leading)
    }

    private func value(_ text: String) -> some View {
        Text(text)
            .textSelection(.enabled)
            .gridColumnAlignment(.leading)
    }

    // MARK: - Notices

    private func noticeRow(icon: String, tint: Color, title: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(tint)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(PIHFont.bodySemibold)
                Text(text)
                    .font(PIHFont.caption)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                .fill(tint.opacity(0.09))
        )
        .overlay(
            RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                .strokeBorder(tint.opacity(0.28), lineWidth: 1)
        )
    }

    private func errorCard(_ error: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            noticeRow(icon: "xmark.octagon.fill", tint: .red, title: "错误详情", text: error)
            if let requestID = model.requestID {
                Text("X-Request-ID：\(requestID)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
    }

    private var stderrCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            DisclosureGroup(isExpanded: $stderrExpanded) {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(model.stderrTail.enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(PIHFont.metaMono)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.top, 8)
            } label: {
                Text("Sidecar stderr 尾部（已过滤 Token）")
                    .font(PIHFont.bodyMedium)
            }
        }
        .pihCard(padding: 16)
        .background(
            RoundedRectangle(cornerRadius: PIHRadius.card, style: .continuous)
                .fill(PIHColor.elevatedSurface)
        )
    }

    private var emptyHint: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("尚未连接")
                .font(PIHFont.bodySemibold)
            Text("点击上方“启动”，App 会生成一次性 Token、以子进程方式拉起 Backend，并读取 stdout 握手后请求 /health。所有状态均来自真实进程与响应。")
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .pihCard(padding: 16)
    }

    // MARK: - Formatting

    private var pidText: String {
        guard let pid = model.processID else { return "—" }
        return model.processRunning ? "\(pid)" : "\(pid)（已退出）"
    }

    private var databaseText: String {
        guard let status = model.databaseStatus else { return "—" }
        if let code = model.databaseCode, !code.isEmpty {
            return "\(status)（\(code)）"
        }
        return status
    }

    private var uptimeText: String {
        guard let seconds = model.uptimeSeconds else { return "—" }
        let total = Int(seconds.rounded(.down))
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let secs = total % 60
        if hours > 0 {
            return "\(hours) 小时 \(minutes) 分 \(secs) 秒"
        }
        if minutes > 0 {
            return "\(minutes) 分 \(secs) 秒"
        }
        return String(format: "%.1f 秒", seconds)
    }

    private func timeText(_ date: Date?) -> String {
        guard let date else { return "—" }
        let formatted = date.formatted(
            .dateTime.year().month().day().hour().minute().second()
        )
        return "\(formatted)（\(TimeZone.current.identifier)）"
    }
}
