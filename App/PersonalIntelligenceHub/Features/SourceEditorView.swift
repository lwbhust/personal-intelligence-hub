import SwiftUI

struct SourceEditorView: View {
    @ObservedObject var store: SourcesStore
    @State private var draft: SourceDraft
    @Environment(\.dismiss) private var dismiss

    init(store: SourcesStore, draft: SourceDraft) {
        self.store = store
        _draft = State(initialValue: draft)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let message = store.errorMessage {
                        ErrorBanner(
                            message: message,
                            requestID: store.errorRequestID,
                            onRetry: nil,
                            onDismiss: { store.clearError() }
                        )
                    }
                    basicFields
                    metadataFields
                    behaviourFields
                }
                .padding(24)
            }
            Divider()
            footer
        }
        .frame(width: 600, height: 700)
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(draft.isEditing ? "编辑信息源" : "新增信息源")
                    .font(PIHFont.subsectionTitle)
                Text("保存后会真实写入本地 SQLite；采集只在手动触发或调度到期时发生。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 18)
    }

    private var basicFields: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("基本信息").font(PIHFont.cardTitle)
            field("名称", error: store.fieldErrors["name"]) {
                TextField("例如：OpenAI Blog", text: $draft.name)
            }
            HStack(alignment: .top, spacing: 12) {
                field("类型", error: store.fieldErrors["source_type"]) {
                    Picker("", selection: $draft.sourceType) {
                        ForEach(SourceType.allCases) { type in
                            Text(type.label).tag(type)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 170)
                }
                field("分类", error: store.fieldErrors["category_id"]) {
                    Picker("", selection: $draft.categoryID) {
                        Text("未分类").tag(String?.none)
                        ForEach(store.categories) { category in
                            Text(category.name).tag(Optional(category.id))
                        }
                    }
                    .labelsHidden()
                    .frame(width: 200)
                }
                Spacer()
            }
            field("URL（Feed / API / 主页）", error: store.fieldErrors["url"]) {
                TextField("https://example.com/feed.xml", text: $draft.url)
            }
            field("主页（可选）", error: store.fieldErrors["homepage_url"]) {
                TextField("https://example.com", text: $draft.homepageURL)
            }
            field("备注（可选）", error: store.fieldErrors["description"]) {
                TextField("用途、语言、更新频率等", text: $draft.description, axis: .vertical)
                    .lineLimit(2...4)
            }
        }
    }

    private var metadataFields: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("元数据").font(PIHFont.cardTitle)
            HStack(alignment: .top, spacing: 12) {
                field("语言（如 zh-CN）", error: store.fieldErrors["language"]) {
                    TextField("zh-CN", text: $draft.language)
                        .frame(width: 150)
                }
                field("国家（两位代码）", error: store.fieldErrors["country"]) {
                    TextField("CN", text: $draft.country)
                        .frame(width: 120)
                }
                Spacer()
            }
            HStack(alignment: .top, spacing: 12) {
                field("优先级（0–100）", error: store.fieldErrors["priority"]) {
                    TextField("0", value: $draft.priority, format: .number)
                        .frame(width: 100)
                }
                field("采集间隔（分钟）", error: store.fieldErrors["fetch_interval_minutes"]) {
                    TextField("60", value: $draft.interval, format: .number)
                        .frame(width: 100)
                }
                Spacer()
            }
            HStack(alignment: .top, spacing: 12) {
                field("单次入库上限（条，可空）", error: store.fieldErrors["max_entries_per_fetch"]) {
                    TextField("默认 100", text: $draft.maxEntries)
                        .frame(width: 100)
                }
                Spacer()
            }
            field("主观权重（0–100，可空）", error: store.fieldErrors["credibility_score"]) {
                TextField("仅代表你的偏好，不是系统评分", text: $draft.credibility)
                    .frame(width: 240)
            }
        }
    }

    private var behaviourFields: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("行为").font(PIHFont.cardTitle)
            Toggle("启用该信息源", isOn: $draft.enabled)
                .toggleStyle(.switch)
            Text("启用后会参与「采集全部」与定时采集；停用只保留历史文章，不再抓取。")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var footer: some View {
        HStack {
            Spacer()
            Button("取消") { dismiss() }
                .keyboardShortcut(.cancelAction)
            Button {
                Task {
                    if await store.save(draft) {
                        dismiss()
                    }
                }
            } label: {
                if store.isSaving {
                    ProgressView().controlSize(.small)
                } else {
                    Text("保存")
                }
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(store.isSaving)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    private func field<Content: View>(
        _ title: String,
        error: String?,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(PIHFont.caption)
                .foregroundStyle(.secondary)
            content()
            FieldErrorText(message: error)
        }
    }
}
