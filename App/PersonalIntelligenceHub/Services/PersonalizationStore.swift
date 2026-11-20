import Foundation

/// 个人智能信息筛选状态与操作。所有数据来自真实 API；错误原样展示。
@MainActor
final class PersonalizationStore: ObservableObject {
    @Published private(set) var profile: PersonalProfileResponseDTO?
    @Published private(set) var interests: [InterestDTO] = []
    @Published private(set) var feed: PersonalFeedDTO?
    @Published private(set) var stats: PersonalStatsDTO?
    @Published private(set) var digest: DailyDigestDTO?
    @Published private(set) var digestHistory: [DailyDigestDTO] = []
    @Published private(set) var suggestions: SuggestionsDTO?
    @Published private(set) var blockedSources: [BlockedSourceDTO] = []

    @Published private(set) var isLoading = false
    @Published private(set) var isRefreshing = false
    @Published private(set) var isGeneratingDigest = false
    @Published private(set) var hasLoaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var actionMessage: String?
    @Published private(set) var actionErrorMessage: String?
    @Published private(set) var pendingFeedbackTarget: String?
    @Published private(set) var feedbackByTarget: [String: String] = [:]

    private weak var client: APIClient?

    func bind(_ client: APIClient?) {
        if client === self.client { return }
        self.client = client
        if client == nil {
            hasLoaded = false
            feed = nil
            profile = nil
            interests = []
            stats = nil
            digest = nil
            digestHistory = []
            suggestions = nil
            blockedSources = []
            feedbackByTarget = [:]
        }
    }

    func loadIfNeeded() async {
        guard client != nil, !hasLoaded, !isLoading else { return }
        await load()
    }

    func load() async {
        guard let client else { return }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            async let profile = client.fetchPersonalProfile()
            async let interests = client.fetchInterests()
            async let feed = client.fetchPersonalFeed()
            async let stats = client.fetchPersonalStats()
            async let blocked = client.fetchBlockedSources()
            self.profile = try await profile
            self.interests = try await interests.items
            self.feed = try await feed
            self.stats = try await stats
            self.blockedSources = try await blocked.items
            self.hasLoaded = true
            await loadSuggestions()
        } catch {
            errorMessage = Self.describe(error)
        }
    }

    func refresh() async {
        guard let client else { return }
        isRefreshing = true
        actionMessage = nil
        defer { isRefreshing = false }
        do {
            async let feed = client.fetchPersonalFeed()
            async let stats = client.fetchPersonalStats()
            self.feed = try await feed
            self.stats = try await stats
            self.interests = try await client.fetchInterests().items
            await loadSuggestions()
            actionMessage = "推荐已刷新（\(Self.timeLabel())）"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func loadSuggestions() async {
        guard let client else { return }
        suggestions = try? await client.fetchSuggestions()
    }

    // MARK: - Interests

    func createInterest(_ payload: InterestCreatePayload) async -> Bool {
        guard let client else { return false }
        actionErrorMessage = nil
        do {
            _ = try await client.createInterest(payload)
            await reloadInterests()
            await refreshAfterPreferenceChange()
            return true
        } catch {
            actionErrorMessage = Self.describe(error)
            return false
        }
    }

    func updateInterest(id: String, payload: InterestUpdatePayload) async -> Bool {
        guard let client else { return false }
        actionErrorMessage = nil
        do {
            _ = try await client.updateInterest(id: id, payload: payload)
            await reloadInterests()
            await refreshAfterPreferenceChange()
            return true
        } catch {
            actionErrorMessage = Self.describe(error)
            return false
        }
    }

    func deleteInterest(id: String) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            try await client.deleteInterest(id: id)
            await reloadInterests()
            await refreshAfterPreferenceChange()
            actionMessage = "兴趣已删除"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func updateKeywords(id: String, keywords: [String], exclusions: [String]) async -> Bool {
        guard let client else { return false }
        actionErrorMessage = nil
        do {
            _ = try await client.updateInterestKeywords(
                id: id, keywords: keywords, exclusions: exclusions
            )
            await reloadInterests()
            await refreshAfterPreferenceChange()
            return true
        } catch {
            actionErrorMessage = Self.describe(error)
            return false
        }
    }

    func linkEntity(interestId: String, entityId: String) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            _ = try await client.linkInterestEntity(interestId: interestId, entityId: entityId)
            await reloadInterests()
            await refreshAfterPreferenceChange()
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func unlinkEntity(interestId: String, entityId: String) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            _ = try await client.unlinkInterestEntity(interestId: interestId, entityId: entityId)
            await reloadInterests()
            await refreshAfterPreferenceChange()
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func searchEntities(_ query: String) async -> [(id: String, name: String, type: String)] {
        guard let client else { return [] }
        return (try? await client.searchEntities(query: query)) ?? []
    }

    func updateProfile(_ payload: ProfileUpdatePayload) async -> Bool {
        guard let client else { return false }
        actionErrorMessage = nil
        do {
            profile = try await client.updatePersonalProfile(payload)
            await refresh()
            return true
        } catch {
            actionErrorMessage = Self.describe(error)
            return false
        }
    }

    func completeOnboarding() async {
        _ = await updateProfile(ProfileUpdatePayload(onboardingDone: true))
    }

    func blockSource(_ sourceId: String, reason: String?) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            blockedSources = try await client.blockSource(sourceId: sourceId, reason: reason).items
            await refresh()
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func unblockSource(_ sourceId: String) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            blockedSources = try await client.unblockSource(sourceId: sourceId).items
            await refresh()
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func applySuggestion(_ suggestion: InterestSuggestionDTO) async {
        _ = await updateInterest(
            id: suggestion.interestId,
            payload: InterestUpdatePayload(level: suggestion.suggestedLevel, weight: suggestion.suggestedWeight)
        )
        actionMessage = "已应用对「\(suggestion.interestName)」的建议"
    }

    private func reloadInterests() async {
        guard let client else { return }
        interests = (try? await client.fetchInterests().items) ?? interests
        profile = try? await client.fetchPersonalProfile()
    }

    private func refreshAfterPreferenceChange() async {
        guard let client else { return }
        feed = try? await client.fetchPersonalFeed()
        stats = try? await client.fetchPersonalStats()
        await loadSuggestions()
    }

    // MARK: - Feedback

    /// 加入稍后阅读：写入真实阅读状态，并从今日流中移出（后端按 later 过滤）。
    func markArticleLater(targetId: String) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            _ = try await client.markArticleLater(id: targetId)
            feed = try? await client.fetchPersonalFeed()
            stats = try? await client.fetchPersonalStats()
            actionMessage = "已加入稍后阅读"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func submitFeedback(targetType: String, targetId: String, feedback: String) async {
        guard let client else { return }
        let key = "\(targetType):\(targetId)"
        pendingFeedbackTarget = key
        actionErrorMessage = nil
        defer { pendingFeedbackTarget = nil }
        do {
            let response = try await client.submitPersonalFeedback(
                targetType: targetType, targetId: targetId, feedback: feedback
            )
            feedbackByTarget[key] = response.feedback.feedback
            feed = try? await client.fetchPersonalFeed()
            stats = try? await client.fetchPersonalStats()
            actionMessage = "已记录反馈：\(Self.feedbackLabel(feedback))"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func revokeFeedback(targetType: String, targetId: String) async {
        guard let client else { return }
        let key = "\(targetType):\(targetId)"
        actionErrorMessage = nil
        do {
            try await client.revokePersonalFeedback(targetType: targetType, targetId: targetId)
            feedbackByTarget.removeValue(forKey: key)
            feed = try? await client.fetchPersonalFeed()
            actionMessage = "已撤销反馈"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func resetPersonalization(clearInterests: Bool, clearFeedback: Bool, clearDigests: Bool) async {
        guard let client else { return }
        actionErrorMessage = nil
        do {
            _ = try await client.resetPersonalization(
                clearInterests: clearInterests,
                clearFeedback: clearFeedback,
                clearDigests: clearDigests
            )
            feedbackByTarget = [:]
            digest = nil
            digestHistory = []
            suggestions = nil
            await reloadInterests()
            await load()
            actionMessage = "已清除所选个人数据"
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    // MARK: - Digest

    func loadTodayDigest(force: Bool = false) async {
        guard let client else { return }
        isGeneratingDigest = true
        actionErrorMessage = nil
        defer { isGeneratingDigest = false }
        do {
            digest = force
                ? try await client.generateDigest(force: true)
                : try await client.fetchTodayDigest(generate: true)
            digestHistory = try await client.fetchDigestHistory(limit: 20).items
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func loadDigest(date: String) async {
        guard let client else { return }
        isGeneratingDigest = true
        actionErrorMessage = nil
        defer { isGeneratingDigest = false }
        do {
            digest = try await client.fetchDigest(date: date, generate: true)
        } catch {
            actionErrorMessage = Self.describe(error)
        }
    }

    func clearActionMessage() {
        actionMessage = nil
    }

    static func describe(_ error: Error) -> String {
        if let api = error as? APIRequestError {
            return api.message
        }
        return APIClient.describe(error)
    }

    static func feedbackLabel(_ value: String) -> String {
        switch value {
        case "interested": return "感兴趣"
        case "not_interested": return "不感兴趣"
        case "important": return "非常重要"
        case "duplicate": return "重复内容"
        case "source_disliked": return "不喜欢来源"
        case "later": return "暂不处理"
        default: return value
        }
    }

    static func timeLabel() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date())
    }
}
