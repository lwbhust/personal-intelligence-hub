import SwiftUI

/// 来源健康日志的目标（用于 sheet item 与无障碍文案）。
struct SourceHealthTarget: Identifiable, Hashable, Sendable {
    let sourceID: String
    let sourceName: String

    var id: String { sourceID }
}

/// 展示 `GET /api/v1/sources/{id}/health?limit=20` 的真实健康日志。
struct SourceHealthSheet: View {
    let target: SourceHealthTarget
    let client: APIClient?

    @Environment(\.dismiss) private var dismiss
    @State private var page: SourceHealthLogPage?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var errorRequestID: String?

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
            Divider()
            footer
        }
        .frame(width: 720, height: 560)
        .task { await load() }
    }

    // MARK: - Header / footer

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("来源健康日志")
                    .font(PIHFont.subsectionTitle)
                Text(target.sourceName)
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            Button {
                Task { await load() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .help("刷新健康日志")
            .disabled(isLoading)
            Button("关闭") { dismiss() }
                .keyboardShortcut(.cancelAction)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var footer: some View {
        HStack {
            if let page {
                Text("显示最近 \(page.items.count) 条 / 共 \(page.total) 条")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("数据来自 /api/v1/sources/{id}/health")
                .font(PIHFont.meta)
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        if client == nil {
            EmptyPanel(
                icon: "bolt.horizontal.circle",
                title: "本地服务未就绪",
                message: "健康日志需要 Sidecar 正常运行。",
                actionTitle: nil,
                action: nil
            )
        } else if isLoading && page == nil {
            VStack(spacing: 8) {
                ProgressView()
                Text("正在加载健康日志…")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let errorMessage, page == nil {
            EmptyPanel(
                icon: "exclamationmark.triangle",
                title: "健康日志加载失败",
                message: errorMessage,
                actionTitle: "重试",
                action: { Task { await load() } }
            )
        } else if let page, page.items.isEmpty {
            EmptyPanel(
                icon: "waveform.path.ecg",
                title: "暂无健康记录",
                message: "该来源还没有可记录的健康检查结果。执行一次采集后会出现真实日志。",
                actionTitle: nil,
                action: nil
            )
        } else if let page {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    if let errorMessage {
                        ErrorBanner(
                            message: errorMessage,
                            requestID: errorRequestID,
                            onRetry: { Task { await load() } },
                            onDismiss: {
                                self.errorMessage = nil
                                self.errorRequestID = nil
                            }
                        )
                        .padding(.bottom, 8)
                    }
                    columnHeader
                    Divider()
                    ForEach(Array(page.items.enumerated()), id: \.offset) { _, log in
                        HealthLogRow(log: log)
                        Divider()
                    }
                }
                .padding(16)
            }
        }
    }

    private var columnHeader: some View {
        HStack(spacing: 10) {
            Text("检查时间").frame(width: 170, alignment: .leading)
            Text("状态").frame(width: 62, alignment: .leading)
            Text("HTTP").frame(width: 48, alignment: .leading)
            Text("延迟").frame(width: 72, alignment: .leading)
            Text("错误").frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(PIHFont.meta.weight(.semibold))
        .foregroundStyle(.secondary)
        .padding(.bottom, 8)
    }

    // MARK: - Loading

    private func load() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let loaded = try await client.fetchSourceHealth(id: target.sourceID, limit: 20)
            page = loaded
            errorMessage = nil
            errorRequestID = nil
        } catch {
            if let api = error as? APIRequestError {
                errorMessage = api.message
                errorRequestID = api.requestID
            } else {
                errorMessage = error.localizedDescription
                errorRequestID = nil
            }
        }
    }
}

private struct HealthLogRow: View {
    let log: SourceHealthLogDTO

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(PIHDateFormat.displayDetailed(log.checkedAt))
                .frame(width: 170, alignment: .leading)
            let status = SourceHealthStatus(rawValue: log.status)
            StatusPill(text: status?.label ?? log.status, tint: status?.tint ?? .secondary)
                .frame(width: 62, alignment: .leading)
            Text(log.httpStatus.map(String.init) ?? "—")
                .frame(width: 48, alignment: .leading)
            Text(PIHDuration.display(log.latencyMs))
                .frame(width: 72, alignment: .leading)
            VStack(alignment: .leading, spacing: 2) {
                if let code = log.errorCode, !code.isEmpty {
                    Text(code)
                        .font(.caption.weight(.medium))
                        .textSelection(.enabled)
                }
                if let message = log.errorMessage, !message.isEmpty {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if (log.errorCode ?? "").isEmpty && (log.errorMessage ?? "").isEmpty {
                    Text("—").foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .font(PIHFont.caption)
        .padding(.vertical, 9)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(PIHDateFormat.displayDetailed(log.checkedAt))，状态 "
                + SourceHealthStatus.label(for: log.status)
        )
    }
}
