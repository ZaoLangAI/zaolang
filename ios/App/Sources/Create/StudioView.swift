import PhotosUI
import SwiftUI
import ZaolangKit

/// 工作台：新建 / 二创一体两态，靠 `StudioMode` 区分（`roadmap.md` D3/D4）。
/// 402pt 单列布局：预览/来源在顶，参数分组纵向排列，报价与提交固定在底部安全区之上。
struct StudioView: View {
    @Environment(AppEnvironment.self) private var environment
    let mode: StudioMode
    let onSubmitted: (String) -> Void

    @State private var viewModel: StudioViewModel?
    @State private var pickerItem: PhotosPickerItem?

    var body: some View {
        Group {
            if let viewModel {
                formBody(viewModel)
            } else {
                ProgressView()
            }
        }
        .navigationTitle(navigationTitle)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel == nil {
                viewModel = StudioViewModel(mode: mode, environment: environment)
            }
            await viewModel?.load()
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task {
                guard let data = try? await item.loadTransferable(type: Data.self) else { return }
                await viewModel?.uploadReference(data: data, filename: "reference.jpg", mimeType: "image/jpeg")
            }
        }
    }

    private var navigationTitle: String {
        switch mode {
        case .new: L10n.t("createPage.title")
        case .remix: L10n.t("remixPage.eyebrow")
        }
    }

    private func formBody(_ viewModel: StudioViewModel) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                sourceSection(viewModel)
                operationSection(viewModel)
                promptSection(viewModel)
                if viewModel.needsReferenceImage {
                    referenceSection(viewModel)
                }
                aspectAndDurationSection(viewModel)
                qualitySection(viewModel)
                if viewModel.sourceWorkID != nil {
                    rightsSection(viewModel)
                }
            }
            .padding(16)
            .padding(.bottom, 120)
        }
        .safeAreaInset(edge: .bottom) { bottomBar(viewModel) }
    }

    @ViewBuilder
    private func sourceSection(_ viewModel: StudioViewModel) -> some View {
        if viewModel.sourceWorkID != nil {
            if viewModel.isLoadingSource {
                RoundedRectangle.zl(ZLRadius.md).fill(Color.zl.skeleton).zlSkeletonPulse().frame(height: 72)
            } else if let source = viewModel.sourceWork {
                HStack(spacing: 12) {
                    RemoteImage(url: source.coverURL.flatMap(URL.init), aspectRatio: 1)
                        .frame(width: 56, height: 56)
                        .zlCornerRadius(ZLRadius.sm)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(L10n.t("remixPage.titleFrom", ["title": source.title]))
                            .font(.subheadline.weight(.medium))
                            .lineLimit(1)
                        Text(source.author.displayName).font(.caption).foregroundStyle(Color.zl.textMuted)
                    }
                    Spacer()
                }
                .padding(12)
                .background(Color.zl.surface)
                .zlCornerRadius(ZLRadius.md)
            } else if let error = viewModel.sourceLoadError {
                Text(error.fallbackMessage).font(.footnote).foregroundStyle(Color.zl.danger)
            }
        }
    }

    private func operationSection(_ viewModel: StudioViewModel) -> some View {
        Picker(L10n.t("createPage.title"), selection: Binding(
            get: { viewModel.operation },
            set: { newValue in
                viewModel.operation = newValue
                viewModel.scheduleQuote()
            }
        )) {
            Text(L10n.t("createPage.modeTextToVideoTitle")).tag(Operation.textToVideo)
            Text(L10n.t("createPage.modeImageToVideoTitle")).tag(Operation.imageToVideo)
        }
        .pickerStyle(.segmented)
    }

    private func promptSection(_ viewModel: StudioViewModel) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("remixPage.promptLabel")).font(.subheadline.weight(.semibold))
            TextField(
                L10n.t("remixPage.promptPlaceholder"),
                text: Binding(get: { viewModel.prompt }, set: { viewModel.prompt = $0 }),
                axis: .vertical
            )
            .lineLimit(3...8)
            .textFieldStyle(.roundedBorder)
        }
    }

    private func referenceSection(_ viewModel: StudioViewModel) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("remixPage.firstFrame")).font(.subheadline.weight(.semibold))
            if let asset = viewModel.referenceAsset {
                HStack(spacing: 12) {
                    RemoteImage(url: asset.url.flatMap(URL.init), aspectRatio: 1)
                        .frame(width: 64, height: 64)
                        .zlCornerRadius(ZLRadius.sm)
                    Button(role: .destructive) { viewModel.removeReference() } label: {
                        Image(systemName: "trash")
                    }
                    Spacer()
                }
            } else {
                let isUploading = viewModel.isUploadingReference
                PhotosPicker(selection: $pickerItem, matching: .images) {
                    HStack {
                        if isUploading {
                            ProgressView()
                        } else {
                            Label(L10n.t("remixPage.addMaterial"), systemImage: "plus")
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 64)
                    .background(Color.zl.surfaceSoft)
                    .zlCornerRadius(ZLRadius.sm)
                }
                .disabled(isUploading)
            }
            if let error = viewModel.uploadError {
                Text(error).font(.caption).foregroundStyle(Color.zl.danger)
            }
        }
    }

    private func aspectAndDurationSection(_ viewModel: StudioViewModel) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 8) {
                Text(L10n.t("remixPage.aspect")).font(.subheadline.weight(.semibold))
                Picker(L10n.t("remixPage.aspect"), selection: Binding(get: { viewModel.aspectRatio }, set: { viewModel.aspectRatio = $0 })) {
                    Text("16:9").tag("16:9")
                    Text("9:16").tag("9:16")
                    Text("1:1").tag("1:1")
                }
                .pickerStyle(.segmented)
            }

            if viewModel.operation.isVideo {
                VStack(alignment: .leading, spacing: 8) {
                    Text(L10n.t("remixPage.duration")).font(.subheadline.weight(.semibold))
                    Stepper(
                        L10n.t("remixPage.durationSeconds", ["count": viewModel.durationSeconds]),
                        value: Binding(
                            get: { viewModel.durationSeconds },
                            set: { newValue in
                                viewModel.durationSeconds = newValue
                                viewModel.scheduleQuote()
                            }
                        ),
                        in: 3...15
                    )
                }
            }
        }
    }

    private func qualitySection(_ viewModel: StudioViewModel) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("remixPage.quality")).font(.subheadline.weight(.semibold))
            Picker(L10n.t("remixPage.quality"), selection: Binding(
                get: { viewModel.qualityTier },
                set: { newValue in
                    viewModel.qualityTier = newValue
                    viewModel.scheduleQuote()
                }
            )) {
                Text(L10n.t("remixPage.tierPreview")).tag(QualityTier.preview)
                Text(L10n.t("remixPage.tierStandard")).tag(QualityTier.standard)
                Text(L10n.t("remixPage.tierCinematic")).tag(QualityTier.cinematic)
            }
            .pickerStyle(.segmented)
        }
    }

    private func rightsSection(_ viewModel: StudioViewModel) -> some View {
        Toggle(isOn: Binding(get: { viewModel.rightsConfirmed }, set: { viewModel.rightsConfirmed = $0 })) {
            Text(L10n.t("remixPage.rightsConfirm")).font(.footnote)
        }
    }

    private func bottomBar(_ viewModel: StudioViewModel) -> some View {
        VStack(spacing: 8) {
            quoteRow(viewModel)
            if let error = viewModel.submitError {
                Text(error).font(.caption).foregroundStyle(Color.zl.danger)
            }
            Button {
                Task {
                    await viewModel.submit()
                    if let jobID = viewModel.submittedJobID {
                        onSubmitted(jobID)
                    }
                }
            } label: {
                HStack {
                    Spacer()
                    if viewModel.isSubmitting {
                        ProgressView()
                    } else {
                        Text(L10n.t("remixPage.submit")).font(.body.weight(.semibold))
                    }
                    Spacer()
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!viewModel.canSubmit)
        }
        .padding(.horizontal, 16)
        .padding(.top, 8)
        .background(.bar)
    }

    @ViewBuilder
    private func quoteRow(_ viewModel: StudioViewModel) -> some View {
        if viewModel.isQuoting {
            HStack { ProgressView().controlSize(.small); Spacer() }
        } else if let quote = viewModel.quote {
            HStack {
                Text(L10n.t("credits.amount", ["count": quote.credits]))
                    .font(.subheadline.weight(.semibold))
                Spacer()
                if !quote.sufficient {
                    Text(L10n.t("credits.insufficient"))
                        .font(.caption.weight(.medium))
                        .foregroundStyle(Color.zl.danger)
                }
            }
        } else if let error = viewModel.quoteError {
            Text(error).font(.caption).foregroundStyle(Color.zl.danger)
        }
    }
}
