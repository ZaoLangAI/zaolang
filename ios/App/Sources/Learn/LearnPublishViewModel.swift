import Foundation
import Observation
import ZaolangKit

/// 发表 / 编辑表单 + 我的发表列表，共用一个 ViewModel（与 `LearnPublishView` 一一对应）。
@MainActor
@Observable
final class LearnPublishViewModel {
    private let environment: AppEnvironment
    private var apiClient: APIClient { environment.apiClient }

    var title = ""
    var summary = ""
    var level: LearnPostLevel = .beginner
    private(set) var coverAssetID: String?
    private(set) var coverPreviewURLString: String?
    private(set) var isUploadingCover = false
    private(set) var coverUploadError: String?

    /// 正文 markdown 源码，直接编辑/直接提交，不做任何客户端转换。
    var bodyMarkdown = ""

    private(set) var isInsertingImage = false
    private(set) var insertImageError: String?

    /// 非 nil 表示正在编辑这篇已发表的内容；提交时改调 `updateLearnPost`，成功后状态重置回 `pending`。
    private(set) var editingPostID: String?

    private(set) var isSubmitting = false
    private(set) var submitError: String?
    private(set) var submitMessage: String?

    private(set) var myPostsState: LoadableState<[LearnPostSummary]> = .loading
    private(set) var withdrawingPostID: String?

    /// 创建流程的幂等键复用同一个本地会话 id，直到成功或用户放弃——网络抖动重试
    /// 不会被后端当成用户点了两次；成功后立刻失效并换新，避免下一篇发表复用旧键。
    private var createSessionID = UUID().uuidString

    init(environment: AppEnvironment) {
        self.environment = environment
    }

    var isEditing: Bool { editingPostID != nil }

    var canSubmit: Bool {
        !isSubmitting
            && !isUploadingCover
            && !isInsertingImage
            && !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func loadMyPosts() async {
        myPostsState = .loading
        do {
            let page = try await apiClient.myLearnPosts()
            myPostsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            myPostsState = .failed(error)
        } catch {
            myPostsState = .failed(.unexpectedResponse(status: 0))
        }
    }

    // MARK: - 封面上传

    func uploadCover(data: Data, filename: String, mimeType: String) async {
        isUploadingCover = true
        coverUploadError = nil
        defer { isUploadingCover = false }
        do {
            let asset = try await upload(data: data, filename: filename, mimeType: mimeType)
            coverAssetID = asset.id
            coverPreviewURLString = asset.url
        } catch let error as ApiError {
            coverUploadError = error.fallbackMessage
        } catch {
            coverUploadError = L10n.t("settingsPage.saveFailed")
        }
    }

    func removeCover() {
        coverAssetID = nil
        coverPreviewURLString = nil
    }

    // MARK: - 正文插图

    /// 上传成功后把 `![](learn-asset:{assetId})` 拼到正文末尾——`TextEditor` 拿不到光标位置，
    /// 直接拼到末尾，用户可以自己把这一行剪切挪到想要的位置。
    func insertImage(data: Data, filename: String, mimeType: String) async {
        isInsertingImage = true
        insertImageError = nil
        defer { isInsertingImage = false }
        do {
            let asset = try await upload(data: data, filename: filename, mimeType: mimeType)
            bodyMarkdown += "\n\n![](learn-asset:\(asset.id))\n\n"
        } catch let error as ApiError {
            insertImageError = error.fallbackMessage
        } catch {
            insertImageError = L10n.t("settingsPage.saveFailed")
        }
    }

    private func upload(data: Data, filename: String, mimeType: String) async throws -> AssetResponse {
        let checksum = UploadTransport.sha256Hex(of: data)
        let presign = try await apiClient.presignUpload(UploadPresignRequest(
            filename: filename,
            mimeType: mimeType,
            sizeBytes: data.count,
            checksumSHA256: checksum,
            purpose: .learnMedia
        ))
        try await environment.uploadTransport.put(data: data, to: presign.uploadURL, requiredHeaders: presign.requiredHeaders)
        return try await apiClient.completeUpload(sessionID: presign.uploadSessionID)
    }

    // MARK: - 回填编辑态

    /// 列表只有 `LearnPostSummary`，没有正文；回填前先拉一次详情。
    func startEditing(postID: String) async {
        do {
            let detail = try await apiClient.fetchLearnPost(id: postID)
            editingPostID = detail.id
            title = detail.title
            summary = detail.summary
            level = detail.level
            coverAssetID = detail.coverAssetID
            coverPreviewURLString = detail.coverURL
            bodyMarkdown = detail.bodyMarkdown
            submitError = nil
            submitMessage = nil
        } catch let error as ApiError {
            submitError = error.fallbackMessage
        } catch {
            submitError = L10n.t("settingsPage.saveFailed")
        }
    }

    func cancelEditing() {
        resetForm()
    }

    private func resetForm() {
        editingPostID = nil
        title = ""
        summary = ""
        level = .beginner
        coverAssetID = nil
        coverPreviewURLString = nil
        coverUploadError = nil
        bodyMarkdown = ""
        insertImageError = nil
    }

    // MARK: - 提交

    func submit() async {
        guard canSubmit else { return }
        isSubmitting = true
        submitError = nil
        submitMessage = nil
        defer { isSubmitting = false }

        let payload = LearnPostCreateRequest(
            title: title,
            summary: summary,
            level: level,
            coverAssetID: coverAssetID,
            bodyMarkdown: bodyMarkdown
        )

        do {
            if let editingPostID {
                _ = try await apiClient.updateLearnPost(id: editingPostID, payload)
                submitMessage = L10n.t("learnPage.updateSuccess")
            } else {
                let idempotencyKey = await environment.idempotencyKeys.key(for: createSessionID)
                _ = try await apiClient.createLearnPost(payload, idempotencyKey: idempotencyKey)
                await environment.idempotencyKeys.invalidate(operationID: createSessionID)
                createSessionID = UUID().uuidString
                submitMessage = L10n.t("learnPage.submitSuccess")
            }
            resetForm()
            await loadMyPosts()
        } catch let error as ApiError {
            submitError = error.fallbackMessage
        } catch {
            submitError = L10n.t("settingsPage.saveFailed")
        }
    }

    func withdraw(id: String) async {
        withdrawingPostID = id
        defer { withdrawingPostID = nil }
        do {
            _ = try await apiClient.withdrawLearnPost(id: id)
            await loadMyPosts()
        } catch let error as ApiError {
            submitError = error.fallbackMessage
        } catch {
            submitError = L10n.t("settingsPage.saveFailed")
        }
    }
}
