import SwiftUI

/// 官方网页适配器配置与 dry-run 面板。所有数据来自真实 Sidecar API。
struct SourceAdapterEditorView: View {
    let source: SourceDTO
    let client: APIClient
    let onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draft = AdapterDraft()
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var isDryRunning = false
    @State private var errorMessage: String?
    @State private var dryRun: AdapterDryRunDTO?
    @State private var configured = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let errorMessage {
                        Text(errorMessage)
                            .font(PIHFont.caption)
                            .foregroundStyle(PIHColor.danger)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(PIHColor.danger.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    toggleCard
                    if draft.enabled {
                        configCard
                        dryRunCard
                    }
                }
                .padding(24)
            }
            Divider()
            footer
        }
        .frame(width: 720, height: 760)
        .background(PIHColor.canvas)
        .task { await load() }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("网页适配器")
                    .font(PIHFont.subsectionTitle)
                Text("\(source.name) · \(source.url)")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            if configured {
                StatusPill(
                    text: verificationLabel,
                    tint: verificationTint
                )
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var toggleCard: some View {
        PIHCard {
            VStack(alignment: .leading, spacing: 8) {
                Toggle("启用网页适配器", isOn: $draft.enabled)
                    .toggleStyle(.switch)
                Text("仅用于没有公开 RSS 的官方网页。请求仍遵守 robots.txt、限流与响应体上限；默认只保存摘要，不保存全文。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var configCard: some View {
        PIHCard {
            VStack(alignment: .leading, spacing: 12) {
                Text("列表页与规则").font(PIHFont.cardTitle)
                VStack(alignment: .leading, spacing: 6) {
                    Text("列表页 URL（每行一个，最多 10 个）")
                        .font(PIHFont.caption)
                    TextEditor(text: $draft.listURLsText)
                        .font(PIHFont.meta)
                        .frame(height: 86)
                        .padding(6)
                        .background(PIHColor.surface, in: RoundedRectangle(cornerRadius: 8))
                }
                VStack(alignment: .leading, spacing: 6) {
                    Text("文章链接正则")
                        .font(PIHFont.caption)
                    TextField("例如 /article/\\d+$", text: $draft.linkPattern)
                        .textFieldStyle(.roundedBorder)
                    Text("只匹配同域文章链接；不匹配列表页、导航或搜索结果。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 24) {
                    Stepper("最多翻页 \(draft.maxPages)", value: $draft.maxPages, in: 1...3)
                    Stepper("单次 \(draft.maxEntriesPerRun) 条", value: $draft.maxEntriesPerRun, in: 1...50)
                }
                .font(PIHFont.caption)
                Stepper("请求间隔 \(draft.rateLimitSeconds) 秒", value: $draft.rateLimitSeconds, in: 1...60)
                    .font(PIHFont.caption)
                Toggle("保存全文（默认关闭）", isOn: $draft.fetchFullText)
                    .toggleStyle(.switch)
                if draft.fetchFullText {
                    Text("开启后会保存详情页正文，请先确认站点条款与个人使用范围。")
                        .font(PIHFont.meta)
                        .foregroundStyle(PIHColor.warning)
                }
            }
        }
    }

    @ViewBuilder
    private var dryRunCard: some View {
        PIHCard {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("验证结果").font(PIHFont.cardTitle)
                    Spacer()
                    Button {
                        Task { await saveAndDryRun() }
                    } label: {
                        if isDryRunning {
                            ProgressView().controlSize(.small)
                        } else {
                            Label("保存并验证", systemImage: "checkmark.seal")
                        }
                    }
                    .disabled(isSaving || isDryRunning)
                }
                if let dryRun {
                    Text("建议状态：\(dryRun.suggestion) · HTTP \(dryRun.httpStatus.map(String.init) ?? "—") · \(dryRun.durationMs) ms")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                    if dryRun.entries.isEmpty {
                        Text("没有解析到条目，请检查列表页、链接正则或站点是否变更。")
                            .font(PIHFont.caption)
                            .foregroundStyle(PIHColor.warning)
                    }
                    ForEach(Array(dryRun.entries.enumerated()), id: \.offset) { _, entry in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(entry.title).font(PIHFont.bodySemibold).lineLimit(2)
                            Text("\(entry.publishedAt ?? "无日期") · 摘要 \(entry.summaryChars) 字 · \(entry.contentState)")
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                    ForEach(dryRun.errors, id: \.self) { item in
                        Text(item)
                            .font(PIHFont.meta)
                            .foregroundStyle(PIHColor.warning)
                    }
                } else {
                    Text("验证只抓取并解析，不写入文章。至少连续 3 次解析出 3 条以上再启用。")
                        .font(PIHFont.meta)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var footer: some View {
        HStack {
            if configured {
                Button("删除适配器", role: .destructive) {
                    Task { await remove() }
                }
                .disabled(isSaving || isDryRunning)
            }
            Spacer()
            Button("取消") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button("保存") {
                Task { await save(silent: false) }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isSaving || isDryRunning || !isValid)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    private var isValid: Bool {
        draft.enabled && !draft.listURLs.isEmpty
            && !draft.linkPattern.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var verificationLabel: String {
        switch draft.lastVerification {
        case "verified": return "已验证"
        case "blocked": return "被站点阻断"
        case "selector_drift": return "需检查选择器"
        default: return "未验证"
        }
    }

    private var verificationTint: Color {
        switch draft.lastVerification {
        case "verified": return .green
        case "blocked", "selector_drift": return PIHColor.warning
        default: return .gray
        }
    }

    private func load() async {
        guard !isLoading else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let record = try await client.fetchAdapter(sourceID: source.id)
            draft = AdapterDraft(record: record)
            configured = true
            errorMessage = nil
        } catch let api as APIRequestError where api.code == "adapter_not_found" {
            draft = AdapterDraft()
            configured = false
            errorMessage = nil
        } catch {
            errorMessage = message(error)
        }
    }

    private func save(silent: Bool) async -> Bool {
        guard isValid else {
            errorMessage = "请至少填写一个列表页 URL 和链接正则"
            return false
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let record = try await client.saveAdapter(
                sourceID: source.id, body: try draft.payload()
            )
            draft = AdapterDraft(record: record)
            configured = true
            errorMessage = nil
            onSaved()
            if !silent { dismiss() }
            return true
        } catch {
            errorMessage = message(error)
            return false
        }
    }

    private func saveAndDryRun() async {
        guard await save(silent: true) else { return }
        isDryRunning = true
        defer { isDryRunning = false }
        do {
            dryRun = try await client.dryRunAdapter(sourceID: source.id, limit: 3)
            draft.lastVerification = dryRun?.suggestion == "verified" ? "verified" : "selector_drift"
            errorMessage = nil
        } catch {
            errorMessage = message(error)
        }
    }

    private func remove() async {
        isSaving = true
        defer { isSaving = false }
        do {
            try await client.deleteAdapter(sourceID: source.id)
            draft = AdapterDraft()
            configured = false
            dryRun = nil
            errorMessage = nil
            onSaved()
        } catch {
            errorMessage = message(error)
        }
    }

    private func message(_ error: Error) -> String {
        (error as? APIRequestError)?.message ?? error.localizedDescription
    }
}
