import SwiftUI

/// 兴趣画像管理：预算/探索比例、兴趣增删改、关键词、关联实体、屏蔽来源与自适应建议。
struct InterestProfileSheet: View {
    @ObservedObject var store: PersonalizationStore
    @Environment(\.dismiss) private var dismiss

    @State private var editing: InterestDTO?
    @State private var creating = false
    @State private var limitEnabled = false
    @State private var limitValue = 10
    @State private var minutesEnabled = false
    @State private var minutesValue = 10
    @State private var explorationRatio = 0.1
    @State private var autoAdjust = true
    @State private var initialized = false
    @State private var confirmClearFeedback = false
    @State private var confirmResetAll = false
    @State private var levelFilter: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                PageHeader("兴趣画像", subtitle: "本地保存，可随时修改或清除；不会上传到任何外部服务")
                Spacer(minLength: 0)
                Button("完成") { dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
            Divider().overlay(PIHColor.hairline)

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let error = store.actionErrorMessage {
                        Text(error)
                            .font(PIHFont.caption)
                            .foregroundStyle(.red)
                    }
                    if let message = store.actionMessage {
                        Text(message)
                            .font(PIHFont.caption)
                            .foregroundStyle(.secondary)
                    }

                    overviewCard
                    budgetCard
                    suggestionsCard
                    interestsCard
                    blockedCard
                    privacyCard
                }
                .padding(24)
                .frame(maxWidth: 820, alignment: .leading)
            }
        }
        .frame(width: 860, height: 680)
        .background(PIHColor.canvas)
        .task {
            guard !initialized else { return }
            initialized = true
            if let profile = store.profile?.profile {
                limitEnabled = profile.dailyItemLimit != nil
                limitValue = profile.dailyItemLimit ?? 10
                minutesEnabled = profile.dailyMinutes != nil
                minutesValue = profile.dailyMinutes ?? 10
                explorationRatio = profile.explorationRatio
                autoAdjust = profile.autoAdjustEnabled
            }
        }
        .confirmationDialog(
            "清除全部反馈记录？该操作不可撤销。",
            isPresented: $confirmClearFeedback,
            titleVisibility: .visible
        ) {
            Button("清除反馈", role: .destructive) {
                Task { await store.resetPersonalization(clearInterests: false, clearFeedback: true, clearDigests: false) }
            }
            Button("取消", role: .cancel) {}
        }
        .confirmationDialog(
            "重置兴趣画像将删除兴趣、反馈、推荐结果与日报（不会删除文章/事件/分析）。",
            isPresented: $confirmResetAll,
            titleVisibility: .visible
        ) {
            Button("全部重置", role: .destructive) {
                Task {
                    await store.resetPersonalization(
                        clearInterests: true, clearFeedback: true, clearDigests: true
                    )
                }
            }
            Button("取消", role: .cancel) {}
        }
        .sheet(item: $editing) { interest in
            InterestEditorSheet(store: store, existing: interest)
        }
        .sheet(isPresented: $creating) {
            InterestEditorSheet(store: store, existing: nil)
        }
    }

    // MARK: - Overview

    private var overviewCard: some View {
        PIHCard {
            CardHeader("兴趣概览", icon: "chart.pie") {
                Text("\(store.interests.count) 个兴趣")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
            }
            HStack(alignment: .bottom, spacing: 22) {
                ForEach(InterestLevel.allCases) { level in
                    let count = store.interests.filter { $0.level == level.rawValue }.count
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(count)")
                            .font(.system(size: 20, weight: .semibold))
                            .monospacedDigit()
                        Text(level.title)
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 8)
                if let profile = store.profile?.profile {
                    Text(
                        "阅读预算："
                        + (profile.dailyItemLimit.map { "\($0) 条" } ?? "未限条数")
                        + " · "
                        + (profile.dailyMinutes.map { "\($0) 分钟" } ?? "未限时长")
                    )
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
                }
            }
            HStack(spacing: 8) {
                InterestChip(
                    title: "全部",
                    count: store.interests.count,
                    isSelected: levelFilter == nil
                ) {
                    levelFilter = nil
                }
                ForEach(InterestLevel.allCases) { level in
                    let count = store.interests.filter { $0.level == level.rawValue }.count
                    if count > 0 {
                        InterestChip(
                            title: level.title,
                            count: count,
                            isSelected: levelFilter == level.rawValue
                        ) {
                            levelFilter = level.rawValue
                        }
                    }
                }
                Spacer(minLength: 0)
            }
            Text("点击标签可筛选下方列表；首页的兴趣导航会直接筛选真实推荐结果。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Budget

    private var budgetCard: some View {
        PIHCard {
            CardHeader("阅读预算与探索", icon: "gauge.with.dots.needle.33percent")
            HStack(spacing: 8) {
                Text("快捷预算")
                    .font(PIHFont.body)
                ForEach([5, 10, 20], id: \.self) { value in
                    InterestChip(
                        title: "\(value) 条",
                        isSelected: limitEnabled && limitValue == value
                    ) {
                        limitEnabled = true
                        limitValue = value
                    }
                }
                Spacer(minLength: 0)
                Text("保存后首页立即生效")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
            Toggle("限制每日首选条数", isOn: $limitEnabled)
            if limitEnabled {
                Stepper("每日 \(limitValue) 条", value: $limitValue, in: 1...100)
                    .padding(.leading, 18)
            }
            Toggle("限制每日阅读时长", isOn: $minutesEnabled)
            if minutesEnabled {
                Stepper("每日 \(minutesValue) 分钟", value: $minutesValue, in: 1...600, step: 5)
                    .padding(.leading, 18)
            }
            HStack(spacing: 10) {
                Text("探索比例")
                    .font(PIHFont.body)
                Slider(value: $explorationRatio, in: 0...0.5, step: 0.05)
                Text("\(Int(explorationRatio * 100))%")
                    .font(PIHFont.caption)
                    .monospacedDigit()
                    .frame(width: 44, alignment: .trailing)
            }
            Toggle("允许生成兴趣调整建议（不会自动修改）", isOn: $autoAdjust)
            Text("预算只影响首选推荐数量，不会删除或隐藏其他文章。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("保存设置") {
                    Task {
                        _ = await store.updateProfile(
                            ProfileUpdatePayload(
                                dailyItemLimit: limitEnabled ? limitValue : nil,
                                dailyMinutes: minutesEnabled ? minutesValue : nil,
                                explorationRatio: explorationRatio,
                                autoAdjustEnabled: autoAdjust
                            )
                        )
                        dismiss()
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Suggestions

    @ViewBuilder
    private var suggestionsCard: some View {
        if let suggestions = store.suggestions, !suggestions.items.isEmpty {
            PIHCard {
                CardHeader("系统观察到的兴趣变化", icon: "sparkles")
                Text("这些建议来自你的主动反馈，只作提示；是否调整由你决定。")
                    .font(PIHFont.meta)
                    .foregroundStyle(.secondary)
                ForEach(suggestions.items) { suggestion in
                    HStack(alignment: .top, spacing: 10) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(suggestion.interestName)
                                .font(PIHFont.bodyMedium)
                            Text(
                                "\(InterestLevel(rawValue: suggestion.currentLevel)?.title ?? suggestion.currentLevel) → "
                                + "\(InterestLevel(rawValue: suggestion.suggestedLevel)?.title ?? suggestion.suggestedLevel)"
                                + "（权重 \(String(format: "%.2f", suggestion.currentWeight)) → \(String(format: "%.2f", suggestion.suggestedWeight))）"
                            )
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                            Text(suggestion.reason)
                                .font(PIHFont.meta)
                                .foregroundStyle(.tertiary)
                        }
                        Spacer(minLength: 0)
                        Text("+\(suggestion.positiveFeedback) / -\(suggestion.negativeFeedback)")
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                        Button("应用") {
                            Task { await store.applySuggestion(suggestion) }
                        }
                        .controlSize(.small)
                    }
                    Divider().overlay(PIHColor.hairline)
                }
            }
        }
    }

    // MARK: - Interests

    private var interestsCard: some View {
        PIHCard {
            HStack {
                CardHeader("兴趣列表", icon: "list.bullet.rectangle")
                Spacer(minLength: 0)
                Button {
                    creating = true
                } label: {
                    Label("添加兴趣", systemImage: "plus")
                }
                .controlSize(.small)
            }
            if store.interests.isEmpty {
                Text("还没有兴趣。建议先添加 1–3 个核心关注。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(InterestLevel.allCases) { level in
                let items = store.interests.filter { $0.level == level.rawValue }
                if !items.isEmpty && (levelFilter == nil || levelFilter == level.rawValue) {
                    Text(level.title)
                        .font(PIHFont.meta.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.top, 4)
                    ForEach(items) { interest in
                        HStack(alignment: .top, spacing: 10) {
                            Toggle(
                                "",
                                isOn: Binding(
                                    get: { interest.enabled },
                                    set: { value in
                                        Task {
                                            _ = await store.updateInterest(
                                                id: interest.id,
                                                payload: InterestUpdatePayload(enabled: value)
                                            )
                                        }
                                    }
                                )
                            )
                            .labelsHidden()
                            VStack(alignment: .leading, spacing: 2) {
                                Text(interest.name)
                                    .font(PIHFont.bodyMedium)
                                Text(
                                    "\(interest.interestType) · 权重 \(String(format: "%.2f", interest.weight))"
                                    + (interest.keywords.isEmpty ? "" : " · 关键词：\(interest.keywords.prefix(4).joined(separator: "、"))")
                                )
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                                if !interest.entityNames.isEmpty {
                                    Text("关注实体：" + interest.entityNames.joined(separator: "、"))
                                        .font(PIHFont.meta)
                                        .foregroundStyle(.tertiary)
                                }
                            }
                            Spacer(minLength: 0)
                            Button("编辑") { editing = interest }
                                .controlSize(.small)
                            Button(role: .destructive) {
                                Task { await store.deleteInterest(id: interest.id) }
                            } label: {
                                Image(systemName: "trash")
                            }
                            .buttonStyle(.borderless)
                            .help("删除该兴趣")
                        }
                        Divider().overlay(PIHColor.hairline)
                    }
                }
            }
        }
    }

    // MARK: - Privacy

    private var privacyCard: some View {
        PIHCard {
            CardHeader("隐私与数据", icon: "lock.shield")
            Text("兴趣画像、反馈与推荐结果只保存在本地 SQLite，不会上传到任何外部服务。")
                .font(PIHFont.meta)
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Button("清除全部反馈记录") { confirmClearFeedback = true }
                    .controlSize(.small)
                Button("重置兴趣画像与推荐") { confirmResetAll = true }
                    .controlSize(.small)
                Spacer(minLength: 0)
                Text("不会删除文章、事件或 AI 分析")
                    .font(PIHFont.meta)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    // MARK: - Blocked sources

    private var blockedCard: some View {
        PIHCard {
            CardHeader("屏蔽的信息源", icon: "nosign")
            if store.blockedSources.isEmpty {
                Text("未屏蔽任何来源。可在信息源页面或日报中屏蔽。")
                    .font(PIHFont.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(store.blockedSources) { source in
                HStack {
                    Text(source.name)
                        .font(PIHFont.body)
                    if let reason = source.reason {
                        Text(reason)
                            .font(PIHFont.meta)
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                    Button("取消屏蔽") {
                        Task { await store.unblockSource(source.sourceId) }
                    }
                    .controlSize(.small)
                }
            }
        }
    }
}

// MARK: - Interest editor

struct InterestEditorSheet: View {
    @ObservedObject var store: PersonalizationStore
    let existing: InterestDTO?
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var interestType = "topic"
    @State private var level = "general"
    @State private var weight = 0.3
    @State private var domainKey = "technology"
    @State private var keywords = ""
    @State private var exclusions = ""
    @State private var notes = ""
    @State private var enabled = true
    @State private var entityQuery = ""
    @State private var entityResults: [(id: String, name: String, type: String)] = []
    @State private var loaded = false

    private let types = ["domain", "topic", "keyword", "entity", "source", "event"]
    private let domains: [(key: String, label: String)] = [
        ("technology", "科技"), ("finance", "财经"), ("politics", "政治"),
        ("international", "国际"), ("society", "社会"), ("health", "健康"),
        ("education", "教育"), ("culture", "文化"), ("sports", "体育"), ("other", "其他"),
        ("ai", "人工智能（主题）"), ("academic", "学术研究（主题）"), ("energy", "能源（主题）"),
        ("economy", "经济（主题）"), ("environment", "环境（主题）"), ("security", "安全（主题）"),
        ("military", "军事（主题）"), ("domestic", "国内（主题）"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(existing == nil ? "新建兴趣" : "编辑兴趣")
                Spacer(minLength: 0)
                Button("取消") { dismiss() }
                Button("保存") { Task { await save() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(20)
            Divider().overlay(PIHColor.hairline)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    TextField("兴趣名称（例如：人工智能）", text: $name)
                        .textFieldStyle(.roundedBorder)
                    Picker("对象类型", selection: $interestType) {
                        ForEach(types, id: \.self) { type in
                            Text(typeLabel(type)).tag(type)
                        }
                    }
                    Picker("关注等级", selection: $level) {
                        ForEach(InterestLevel.allCases) { item in
                            Text(item.title).tag(item.rawValue)
                        }
                    }
                    .onChange(of: level) { _, newValue in
                        weight = defaultWeight(newValue)
                    }
                    HStack {
                        Text("权重")
                        Slider(value: $weight, in: 0...1, step: 0.05)
                        Text(String(format: "%.2f", weight))
                            .font(PIHFont.caption)
                            .monospacedDigit()
                            .frame(width: 40, alignment: .trailing)
                    }
                    if interestType == "domain" || interestType == "topic" {
                        Picker("领域/主题", selection: $domainKey) {
                            ForEach(domains, id: \.key) { item in
                                Text(item.label).tag(item.key)
                            }
                        }
                    }
                    TextField("关键词，用中文逗号或英文逗号分隔", text: $keywords)
                        .textFieldStyle(.roundedBorder)
                    TextField("排除关键词（命中后该兴趣不计分）", text: $exclusions)
                        .textFieldStyle(.roundedBorder)
                    TextField("备注（可选）", text: $notes)
                        .textFieldStyle(.roundedBorder)
                    Toggle("启用", isOn: $enabled)

                    if let existing {
                        Divider().overlay(PIHColor.hairline)
                        Text("关注实体").font(PIHFont.bodyMedium)
                        if existing.entityNames.isEmpty {
                            Text("尚未关联实体。")
                                .font(PIHFont.meta)
                                .foregroundStyle(.secondary)
                        }
                        ForEach(Array(existing.entityIds.enumerated()), id: \.element) { index, entityId in
                            HStack {
                                Text(existing.entityNames.indices.contains(index) ? existing.entityNames[index] : entityId)
                                Spacer()
                                Button("移除") {
                                    Task { await store.unlinkEntity(interestId: existing.id, entityId: entityId) }
                                }
                                .controlSize(.small)
                            }
                        }
                        HStack {
                            TextField("搜索实体（名称）", text: $entityQuery)
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { Task { await searchEntities() } }
                            Button("搜索") { Task { await searchEntities() } }
                                .controlSize(.small)
                        }
                        ForEach(entityResults, id: \.id) { item in
                            HStack {
                                Text(item.name)
                                Text(item.type)
                                    .font(PIHFont.meta)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Button("关联") {
                                    Task {
                                        await store.linkEntity(interestId: existing.id, entityId: item.id)
                                        entityResults.removeAll { $0.id == item.id }
                                    }
                                }
                                .controlSize(.small)
                            }
                        }
                    }
                    if let error = store.actionErrorMessage {
                        Text(error)
                            .font(PIHFont.caption)
                            .foregroundStyle(.red)
                    }
                }
                .padding(20)
            }
        }
        .frame(width: 560, height: 640)
        .background(PIHColor.canvas)
        .task {
            guard !loaded else { return }
            loaded = true
            if let existing {
                name = existing.name
                interestType = existing.interestType
                level = existing.level
                weight = existing.weight
                domainKey = existing.domainKey ?? "technology"
                keywords = existing.keywords.joined(separator: "，")
                exclusions = existing.exclusionKeywords.joined(separator: "，")
                notes = existing.notes ?? ""
                enabled = existing.enabled
            }
        }
    }

    private func typeLabel(_ type: String) -> String {
        switch type {
        case "domain": return "领域"
        case "topic": return "技术主题"
        case "keyword": return "关键词"
        case "entity": return "实体"
        case "source": return "信息源"
        case "event": return "事件"
        default: return type
        }
    }

    private func defaultWeight(_ level: String) -> Double {
        switch level {
        case "core": return 1.0
        case "extended": return 0.65
        case "general": return 0.3
        default: return 0.0
        }
    }

    private func splitKeywords(_ text: String) -> [String] {
        text.split(whereSeparator: { $0 == "," || $0 == "，" || $0 == ";" || $0 == "；" })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    private func save() async {
        let keywordList = splitKeywords(keywords)
        let exclusionList = splitKeywords(exclusions)
        if let existing {
            _ = await store.updateInterest(
                id: existing.id,
                payload: InterestUpdatePayload(
                    name: name,
                    level: level,
                    weight: weight,
                    domainKey: (interestType == "domain" || interestType == "topic") ? domainKey : nil,
                    keywords: keywordList,
                    exclusionKeywords: exclusionList,
                    notes: notes,
                    enabled: enabled
                )
            )
        } else {
            _ = await store.createInterest(
                InterestCreatePayload(
                    name: name,
                    interestType: interestType,
                    level: level,
                    domainKey: (interestType == "domain" || interestType == "topic") ? domainKey : nil,
                    keywords: keywordList,
                    exclusionKeywords: exclusionList,
                    notes: notes,
                    enabled: enabled
                )
            )
        }
        dismiss()
    }

    private func searchEntities() async {
        entityResults = await store.searchEntities(entityQuery)
    }
}
