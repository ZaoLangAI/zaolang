import Foundation

/// 上传用途，决定后端把对象放进哪个前缀、套哪条内容审核策略。
public enum UploadPurpose: String, Codable, Sendable, CaseIterable {
    case generationReference = "generation_reference"
    case avatar
    case profileCover = "profile_cover"
    case consentEvidence = "consent_evidence"
}

/// `POST /v1/uploads/presign` 请求体。`checksumSHA256` 必须是上传前对文件全量内容算出的
/// 十六进制小写摘要——后端拿它把签名绑定到这一份具体内容，不是走个形式。
public struct UploadPresignRequest: Encodable, Sendable {
    public var filename: String
    public var mimeType: String
    public var sizeBytes: Int
    public var checksumSHA256: String
    public var purpose: UploadPurpose

    public init(filename: String, mimeType: String, sizeBytes: Int, checksumSHA256: String, purpose: UploadPurpose) {
        self.filename = filename
        self.mimeType = mimeType
        self.sizeBytes = sizeBytes
        self.checksumSHA256 = checksumSHA256
        self.purpose = purpose
    }

    private enum CodingKeys: String, CodingKey {
        case filename
        case mimeType = "mime_type"
        case sizeBytes = "size_bytes"
        case checksumSHA256 = "checksum_sha256"
        case purpose
    }
}

public struct UploadPresignResponse: Codable, Sendable, Equatable {
    public let uploadSessionID: String
    public let uploadURL: String
    public let objectKey: String
    public let expiresAt: Date
    public let requiredHeaders: [String: String]

    private enum CodingKeys: String, CodingKey {
        case uploadSessionID = "upload_session_id"
        case uploadURL = "upload_url"
        case objectKey = "object_key"
        case expiresAt = "expires_at"
        case requiredHeaders = "required_headers"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        uploadSessionID = try c.decode(String.self, forKey: .uploadSessionID)
        uploadURL = try c.decode(String.self, forKey: .uploadURL)
        objectKey = try c.decode(String.self, forKey: .objectKey)
        expiresAt = try c.decode(Date.self, forKey: .expiresAt)
        requiredHeaders = try c.decodeIfPresent([String: String].self, forKey: .requiredHeaders) ?? [:]
    }
}

public struct UploadCompleteRequest: Encodable, Sendable {
    public var uploadSessionID: String

    public init(uploadSessionID: String) {
        self.uploadSessionID = uploadSessionID
    }

    private enum CodingKeys: String, CodingKey {
        case uploadSessionID = "upload_session_id"
    }
}

public struct ProvenanceResponse: Codable, Sendable, Equatable {
    public let assetID: String
    public let generationJobID: String?
    public let claim: [String: JSONValue]
    public let signed: Bool

    private enum CodingKeys: String, CodingKey {
        case assetID = "asset_id"
        case generationJobID = "generation_job_id"
        case claim, signed
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        assetID = try c.decode(String.self, forKey: .assetID)
        generationJobID = try c.decodeIfPresent(String.self, forKey: .generationJobID)
        claim = try c.decodeIfPresent([String: JSONValue].self, forKey: .claim) ?? [:]
        signed = try c.decodeIfPresent(Bool.self, forKey: .signed) ?? false
    }
}
