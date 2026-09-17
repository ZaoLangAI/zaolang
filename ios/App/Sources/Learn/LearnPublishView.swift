import PhotosUI
import SwiftUI
import ZaolangKit

/// 发表 / 编辑学习内容 + 管理"我的发表"，对应 Web `(site)/learn/publish/page.tsx`。
/// 未登录不应能到达这一屏——入口（创作 Tab 卡片、学习页空态出口）都套了 `requireAuth`，
/// 这里不再重复登录墙。
struct LearnPublishView: View {
    @Environment(AppEnvironment.self) private var environment
    let onDone: () -> Void

    @State private var viewModel: LearnPublishViewModel?
    @State private var coverPickerItem: PhotosPickerItem?
    @State private var bodyImagePickerItem: PhotosPickerItem?
    @State private var withdrawTargetID: String?

    var body: some View {
        Group {
            if let viewModel {
                form(viewModel)
            } else {
                ProgressView()
            }
        }
        .navigationTitle(L10n.t("learnPage.publishHeroTitle"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel == nil {
                viewModel = LearnPublishViewModel(environment: environment)
            }
            await viewModel?.loadMyPosts()
        }
        .onChange(of: coverPickerItem) { _, item in
            guard let item else { return }
            Task {
                guard let data = try? await item.loadTransferable(type: Data.self) else { return }
                await viewModel?.uploadCover(data: data, filename: "cover.jpg", mimeType: "image/jpeg")
                coverPickerItem = nil
            }
        }
        .onChange(of: bodyImagePickerItem) { _, item in
            guard let item else { return }
            Task {
                guard let data = try? await item.loadTransferable(type: Data.self) else { return }
                await viewModel?.insertImage(data: data, filename: "body.jpg", mimeType: "image/jpeg")
                bodyImagePickerItem = nil
            }
        }
        .confirmationDialog(
            L10n.t("learnPage.withdrawConfirm"),
            isPresented: Binding(get: { withdrawTargetID != nil }, set: { if !$0 { withdrawTargetID = nil } }),
            titleVisibility: .visible
        ) {
            Button(L10n.t("learnPage.withdrawAction"), role: .destructive) {
                if let id = withdrawTargetID {
                    Task { await viewModel?.withdraw(id: id) }
                }
                withdrawTargetID = nil
            }
            Button(L10n.t("actions.cancel"), role: .cancel) { withdrawTargetID = nil }
        }
    }

    private func form(_ viewModel: LearnPublishViewModel) -> some View {
        Form {
            fieldsSection(viewModel)
            coverSection(viewModel)
            bodySection(viewModel)
            submitSection(viewModel)
            myPostsSection(viewModel)
        }
    }

    private func fieldsSection(_ viewModel: LearnPublishViewModel) -> some View {
        Section {
            TextField(
                L10n.t("learnPage.formTitleLabel"),
                text: Binding(get: { viewModel.title }, set: { viewModel.title = $0 }),
                prompt: Text(L10n.t("learnPage.formTitlePlaceholder"))
            )
            TextField(
                L10n.t("learnPage.formSummaryLabel"),
                text: Binding(get: { viewModel.summary }, set: { viewModel.summary = $0 }),
                prompt: Text(L10n.t("learnPage.formSummaryPlaceholder")),
                axis: .vertical
            )
            Picker(L10n.t("learnPage.formLevelLabel"), selection: Binding(get: { viewModel.level }, set: { viewModel.level = $0 })) {
                Text(L10n.t("learnPage.levelBeginner")).tag(LearnPostLevel.beginner)
                Text(L10n.t("learnPage.levelIntermediate")).tag(LearnPostLevel.intermediate)
                Text(L10n.t("learnPage.levelAdvanced")).tag(LearnPostLevel.advanced)
            }
        }
    }

    private func coverSection(_ viewModel: LearnPublishViewModel) -> some View {
        Section {
            if let urlString = viewModel.coverPreviewURLString, let url = URL(string: urlString) {
                RemoteImage(url: url, aspectRatio: 16.0 / 9.0, contentMode: .fill)
                    .zlCornerRadius(ZLRadius.md)
                    .listRowInsets(EdgeInsets())
                Button(role: .destructive) { viewModel.removeCover() } label: {
                    Text(L10n.t("learnPage.blockRemove"))
                }
            } else {
                PhotosPicker(selection: $coverPickerItem, matching: .images) {
                    HStack {
                        if viewModel.isUploadingCover {
                            ProgressView()
                        } else {
                            Label(L10n.t("remixPage.addMaterial"), systemImage: "photo.badge.plus")
                        }
                    }
                }
                .disabled(viewModel.isUploadingCover)
            }
            if let error = viewModel.coverUploadError {
                Text(error).font(.caption).foregroundStyle(Color.zl.danger)
            }
        } header: {
            Text(L10n.t("learnPage.formCoverLabel"))
        } footer: {
            Text(L10n.t("learnPage.formCoverHint")).font(.caption)
        }
    }

    private func bodySection(_ viewModel: LearnPublishViewModel) -> some View {
        Section {
            bodyEditor(viewModel)

            HStack {
                PhotosPicker(selection: $bodyImagePickerItem, matching: .images) {
                    if viewModel.isInsertingImage {
                        ProgressView()
                    } else {
                        Label(L10n.t("learnPage.insertImage"), systemImage: "photo.badge.plus")
                    }
                }
                .disabled(viewModel.isInsertingImage)
            }
            .buttonStyle(.bordered)
            .font(.caption)

            if let error = viewModel.insertImageError {
                Text(error).font(.caption2).foregroundStyle(Color.zl.danger)
            }
        } header: {
            Text(L10n.t("learnPage.formBodyLabel"))
        } footer: {
            Text(L10n.t("learnPage.bodyMarkdownHint")).font(.caption)
        }
    }

    private func bodyEditor(_ viewModel: LearnPublishViewModel) -> some View {
        TextEditor(text: Binding(get: { viewModel.bodyMarkdown }, set: { viewModel.bodyMarkdown = $0 }))
            .font(.body.monospaced())
            .frame(minHeight: 200)
    }

    private func submitSection(_ viewModel: LearnPublishViewModel) -> some View {
        Section {
            Button {
                Task { await viewModel.submit() }
            } label: {
                HStack {
                    Spacer()
                    if viewModel.isSubmitting {
                        ProgressView()
                    } else {
                        Text(viewModel.isEditing ? L10n.t("learnPage.submitUpdate") : L10n.t("learnPage.submitNew"))
                            .font(.body.weight(.semibold))
                    }
                    Spacer()
                }
            }
            .disabled(!viewModel.canSubmit)

            if viewModel.isEditing {
                Button(L10n.t("learnPage.cancelEdit")) { viewModel.cancelEditing() }
            }

            if let message = viewModel.submitMessage {
                Text(message).font(.footnote).foregroundStyle(Color.zl.text)
            }
            if let error = viewModel.submitError {
                Text(error).font(.footnote).foregroundStyle(Color.zl.danger)
            }
        }
    }

    @ViewBuilder
    private func myPostsSection(_ viewModel: LearnPublishViewModel) -> some View {
        Section(L10n.t("learnPage.myPostsTitle")) {
            switch viewModel.myPostsState {
            case .loading:
                HStack { Spacer(); ProgressView(); Spacer() }
            case .empty:
                EmptyStateView(title: L10n.t("learnPage.myPostsEmpty"), message: L10n.t("learnPage.myPostsEmptyHint"))
                    .listRowInsets(EdgeInsets())
            case .failed(let error):
                ErrorStateView(error: error) { Task { await viewModel.loadMyPosts() } }
                    .listRowInsets(EdgeInsets())
            case .loaded(let posts):
                ForEach(posts) { post in
                    myPostRow(post, viewModel)
                }
            }
        }
    }

    private func myPostRow(_ post: LearnPostSummary, _ viewModel: LearnPublishViewModel) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(post.title).font(.subheadline.weight(.semibold)).lineLimit(1)
                Spacer()
                Text(statusLabel(post.status))
                    .font(.caption2.weight(.medium))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.zl.surfaceSoft)
                    .zlCornerRadius(ZLRadius.sm)
            }
            Text(post.summary).font(.caption).foregroundStyle(Color.zl.textMuted).lineLimit(2)

            HStack(spacing: 16) {
                Button(L10n.t("learnPage.editAction")) {
                    Task { await viewModel.startEditing(postID: post.id) }
                }
                if post.status.value != .withdrawn {
                    Button(L10n.t("learnPage.withdrawAction"), role: .destructive) {
                        withdrawTargetID = post.id
                    }
                    .disabled(viewModel.withdrawingPostID == post.id)
                }
            }
            .font(.caption)
        }
        .padding(.vertical, 4)
    }

    private func statusLabel(_ status: RawOrUnknown<LearnPostStatus>) -> String {
        switch status {
        case .known(let value):
            switch value {
            case .pending: L10n.t("learnPage.statusPending")
            case .approved: L10n.t("learnPage.statusApproved")
            case .rejected: L10n.t("learnPage.statusRejected")
            case .withdrawn: L10n.t("learnPage.statusWithdrawn")
            }
        case .unknown(let raw):
            raw
        }
    }
}
