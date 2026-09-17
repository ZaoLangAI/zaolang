import Foundation
import Security

/// 只存一个字符串（refresh token 原始值）的最小 Keychain 封装。
///
/// 选 `afterFirstUnlockThisDeviceOnly`：不参与 iCloud 备份/迁移到新设备，
/// 但设备重启后首次解锁就能读到，允许锁屏状态下的后台续期。
public final class KeychainStore: Sendable {
    private let service: String
    private let account: String

    public init(service: String = "ai.zaolang.app", account: String = "zl_refresh_token") {
        self.service = service
        self.account = account
    }

    public func read() -> String? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    public func write(_ value: String) {
        let data = Data(value.utf8)
        let updateStatus = SecItemUpdate(
            baseQuery() as CFDictionary,
            [kSecValueData as String: data] as CFDictionary
        )
        guard updateStatus == errSecItemNotFound else { return }

        var addQuery = baseQuery()
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(addQuery as CFDictionary, nil)
    }

    public func delete() {
        SecItemDelete(baseQuery() as CFDictionary)
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}
