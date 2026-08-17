import SwiftUI
import ZaolangKit

/// A minimal shape `LibraryPickerSheet` needs from a character or a scene —
/// just enough to list and pick one. Editing reference images, regenerating a
/// view, or publishing stays on the full library page; this sheet is only
/// the "pick one for this generation" entry point (see the asset-kind plan's
/// "先做到按 view 分组展示 + 选中一张" scope for this round).
protocol LibraryPickable: Identifiable where ID == String {
    var name: String { get }
    var thumbnailURLString: String? { get }
}

extension CharacterResponse: LibraryPickable {
    var thumbnailURLString: String? { frontReference?.url ?? referenceAssets.first?.url }
}

extension SceneResponse: LibraryPickable {
    var thumbnailURLString: String? { referenceAssets.first?.url }
}

/// Lightweight "list existing / create new" picker shared by the character
/// and scene target selectors in the image-creation studio form. Selecting a
/// row (including the leading "none" row) dismisses immediately — this is a
/// picker, not a management screen.
struct LibraryPickerSheet<Item: LibraryPickable>: View {
    let title: String
    let items: [Item]
    let selectedID: String?
    let isLoading: Bool
    let emptyOptionLabel: String
    let newItemTitle: String
    let namePlaceholder: String
    let onSelect: (String?) -> Void
    let onCreate: (String, String?) async -> Void
    /// Only wired for the character sheet — mirrors the web character
    /// library's "补全侧面/背面" card action (`character-library.tsx`'s
    /// `canCompleteViews`/`completeViews`). Rendered as a secondary row
    /// action rather than a dismissing tap, since the user is still picking.
    var canComplete: (Item) -> Bool = { _ in false }
    var completingID: String? = nil
    var onComplete: ((Item) -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var showNewItemSheet = false

    var body: some View {
        NavigationStack {
            List {
                Button {
                    onSelect(nil)
                    dismiss()
                } label: {
                    HStack {
                        Text(emptyOptionLabel).foregroundStyle(Color.zl.text)
                        Spacer()
                        if selectedID == nil {
                            Image(systemName: "checkmark").foregroundStyle(Color.zl.primary)
                        }
                    }
                }
                if isLoading {
                    HStack { Spacer(); ProgressView(); Spacer() }
                } else {
                    ForEach(items) { item in
                        HStack(spacing: 12) {
                            Button {
                                onSelect(item.id)
                                dismiss()
                            } label: {
                                HStack(spacing: 12) {
                                    RemoteImage(url: item.thumbnailURLString.flatMap(URL.init), aspectRatio: 1)
                                        .frame(width: 40, height: 40)
                                        .zlCornerRadius(ZLRadius.sm)
                                    Text(item.name).foregroundStyle(Color.zl.text)
                                    if item.id == selectedID {
                                        Image(systemName: "checkmark").foregroundStyle(Color.zl.primary)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            Spacer()
                            if canComplete(item), let onComplete {
                                Button {
                                    onComplete(item)
                                } label: {
                                    if completingID == item.id {
                                        ProgressView()
                                    } else {
                                        Text(L10n.t("remixPage.completeViews")).font(.caption)
                                    }
                                }
                                .buttonStyle(.bordered)
                                .disabled(completingID != nil)
                            }
                        }
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewItemSheet = true } label: { Image(systemName: "plus") }
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.cancel")) { dismiss() }
                }
            }
            .sheet(isPresented: $showNewItemSheet) {
                NewLibraryItemSheet(title: newItemTitle, namePlaceholder: namePlaceholder) { name, description in
                    Task {
                        await onCreate(name, description)
                        dismiss()
                    }
                }
            }
        }
    }
}

/// Name + optional description — the same minimal shape `NewCollectionSheet`
/// (`LibraryView.swift`) uses for its own "new X" form.
private struct NewLibraryItemSheet: View {
    let title: String
    let namePlaceholder: String
    let onCreate: (String, String?) -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var description = ""

    var body: some View {
        NavigationStack {
            Form {
                TextField(namePlaceholder, text: $name)
                TextField(L10n.t("remixPage.descriptionPlaceholder"), text: $description, axis: .vertical)
                    .lineLimit(2...4)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.t("actions.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.t("actions.confirm")) {
                        onCreate(name, description.isEmpty ? nil : description)
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}
