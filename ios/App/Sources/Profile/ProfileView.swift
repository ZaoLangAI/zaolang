import SwiftUI
import ZaolangKit

/// 个人主页，对应 `04-screens.md` 第 14 屏。私有主页在这一层已经和 404 合并——
/// 后端 `profiles.py` 对未公开主页直接抛 `NotFound`，客户端只看到统一的 `.notFound`。
struct ProfileView: View {
    @Environment(AppEnvironment.self) private var environment
    let handle: String
    let onOpenWork: (String) -> Void
    let onOpenLineage: (String) -> Void

    @State private var viewModel: ProfileViewModel?

    var body: some View {
        content
            .navigationBarTitleDisplayMode(.inline)
            .task {
                if viewModel == nil {
                    viewModel = ProfileViewModel(handle: handle, apiClient: environment.apiClient)
                }
                await viewModel?.load()
            }
    }

    @ViewBuilder
    private var content: some View {
        switch viewModel?.state ?? .loading {
        case .loading:
            ScrollView { skeleton }
        case .empty:
            NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("profilePage.privateProfile"))
        case .failed(let error):
            if error.isOffline {
                ErrorStateView(error: error) { Task { await viewModel?.load() } }
            } else {
                NotFoundView(title: L10n.t("states.notFound"), message: L10n.t("profilePage.privateProfile"))
            }
        case .loaded(let profile):
            body(profile)
        }
    }

    private func body(_ profile: PublicProfileResponse) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header(profile)
                statRow(profile)
                creatorSection(profile)
                worksSection
            }
            .padding(.bottom, 24)
        }
    }

    private func header(_ profile: PublicProfileResponse) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: profile.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 5.0, contentMode: .fill)

            HStack(alignment: .top, spacing: 12) {
                RemoteImage(url: profile.avatarURL.flatMap(URL.init), aspectRatio: 1)
                    .frame(width: 64, height: 64)
                    .clipShape(Circle())
                    .overlay { Circle().strokeBorder(Color.zl.bg, lineWidth: 3) }
                    .offset(y: -24)

                VStack(alignment: .leading, spacing: 2) {
                    Text(profile.displayName).font(.title3.weight(.semibold))
                    Text("@\(profile.handle)").font(.footnote).foregroundStyle(Color.zl.textMuted)
                }
                .padding(.top, 8)

                Spacer()

                Group {
                    if profile.isSelf {
                        Text(L10n.t("profilePage.editProfile"))
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(Color.zl.textMuted)
                    } else {
                        let following = viewModel?.isFollowing ?? profile.viewerFollowing
                        Button {
                            environment.requireAuth(
                                actionLabel: following ? L10n.t("profilePage.unfollow") : L10n.t("profilePage.follow")
                            ) {
                                Task { await viewModel?.toggleFollow(userID: profile.userID) }
                            }
                        } label: {
                            Text(following ? L10n.t("profilePage.following") : L10n.t("profilePage.follow"))
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
                .padding(.top, 8)
            }
            .padding(.horizontal, 16)
        }
    }

    private func statRow(_ profile: PublicProfileResponse) -> some View {
        HStack {
            statTile(profile.workCount, L10n.t("profilePage.statWorks"))
            statTile(viewModel?.viewCount ?? 0, L10n.t("profilePage.statViews"))
            statTile(viewModel?.likeCount ?? 0, L10n.t("profilePage.statLikes"))
            statTile(profile.followerCount, L10n.t("profilePage.statFollowers"))
            statTile(viewModel?.remixCount ?? 0, L10n.t("profilePage.statRemixes"))
        }
        .padding(.horizontal, 16)
    }

    private func statTile(_ value: Int, _ label: String) -> some View {
        VStack(spacing: 2) {
            Text("\(value)").font(.subheadline.weight(.semibold))
            Text(label).font(.caption2).foregroundStyle(Color.zl.textMuted)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }

    private func creatorSection(_ profile: PublicProfileResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L10n.t("profilePage.creatorProfile")).font(.subheadline.weight(.semibold))
            Text(L10n.t("profilePage.creatorProfileHint")).font(.caption2).foregroundStyle(Color.zl.textMuted)
            Text(profile.bio?.isEmpty == false ? profile.bio! : L10n.t("profilePage.noBio"))
                .font(.footnote)
                .foregroundStyle(Color.zl.text)

            if let tags = viewModel?.styleTags, !tags.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) { ForEach(tags, id: \.self) { TagChip(label: $0) } }
                }
            }
        }
        .padding(16)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
        .padding(.horizontal, 16)
    }

    @ViewBuilder
    private var worksSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L10n.t("profilePage.worksTab")).font(.subheadline.weight(.semibold)).padding(.horizontal, 16)

            if let works = viewModel?.works, !works.isEmpty {
                WaterfallGrid(items: works, aspectRatio: { $0.coverAspectRatio }) { work in
                    WorkCardView(work: work, onTapCover: { onOpenWork(work.id) }, onTapAuthor: nil)
                }
                .padding(.horizontal, 16)
            } else {
                EmptyStateView(title: L10n.t("profilePage.noActivity"), message: L10n.t("profilePage.creatorProfileHint"))
            }
        }
    }

    private var skeleton: some View {
        VStack(alignment: .leading, spacing: 16) {
            RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().aspectRatio(16.0 / 5.0, contentMode: .fit)
            HStack {
                Circle().fill(Color.zl.skeleton).zlSkeletonPulse().frame(width: 64, height: 64)
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).zlSkeletonPulse().frame(width: 140, height: 18)
            }
        }
        .padding(16)
    }
}
