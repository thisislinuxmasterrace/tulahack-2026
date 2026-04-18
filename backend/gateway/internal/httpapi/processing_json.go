package httpapi

import (
	"encoding/json"
	"time"

	"tulahack/gateway/internal/store"
)

func processingJobJSON(j store.ProcessingJob) map[string]any {
	out := map[string]any{
		"id":         j.ID.String(),
		"upload_id":  j.UploadID.String(),
		"user_id":    j.UserID.String(),
		"status":     j.Status,
		"created_at": j.CreatedAt.UTC().Format(time.RFC3339Nano),
		"updated_at": j.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}
	if j.Stage != nil {
		out["stage"] = *j.Stage
	}
	if j.ErrorCode != nil {
		out["error_code"] = *j.ErrorCode
	}
	if j.ErrorMessage != nil {
		out["error_message"] = *j.ErrorMessage
	}
	if j.WhisperModel != nil {
		out["whisper_model"] = *j.WhisperModel
	}
	if j.LlmModel != nil {
		out["llm_model"] = *j.LlmModel
	}
	if len(j.WhisperOutput) > 0 {
		out["whisper_output"] = json.RawMessage(j.WhisperOutput)
	}
	if len(j.LlmEntities) > 0 {
		out["llm_entities"] = json.RawMessage(j.LlmEntities)
	}
	if j.TranscriptPlain != nil {
		out["transcript_plain"] = *j.TranscriptPlain
	}
	if j.TranscriptRedacted != nil {
		out["transcript_redacted"] = *j.TranscriptRedacted
	}
	if len(j.RedactionReport) > 0 {
		out["redaction_report"] = json.RawMessage(j.RedactionReport)
	}
	if j.RedactedAudioBucket != nil {
		out["redacted_audio_bucket"] = *j.RedactedAudioBucket
	}
	if j.RedactedAudioObjectKey != nil {
		out["redacted_audio_object_key"] = *j.RedactedAudioObjectKey
	}
	if j.RedactedAudioStorageURL != nil {
		out["redacted_audio_storage_url"] = *j.RedactedAudioStorageURL
	}
	if len(j.ProcessingEvents) > 0 {
		out["processing_events"] = json.RawMessage(j.ProcessingEvents)
	}
	if j.StartedAt != nil {
		out["started_at"] = j.StartedAt.UTC().Format(time.RFC3339Nano)
	}
	if j.FinishedAt != nil {
		out["finished_at"] = j.FinishedAt.UTC().Format(time.RFC3339Nano)
	}
	return out
}

func uploadJSON(u store.AudioUpload) map[string]any {
	return map[string]any{
		"id":                u.ID.String(),
		"user_id":           u.UserID.String(),
		"bucket":            u.Bucket,
		"object_key":        u.ObjectKey,
		"storage_url":       u.StorageURL,
		"original_filename": u.OriginalFilename,
		"content_type":      u.ContentType,
		"byte_size":         u.ByteSize,
		"created_at":        u.CreatedAt.UTC().Format(time.RFC3339Nano),
	}
}

func uploadListItemJSON(item store.UploadListItem) map[string]any {
	row := map[string]any{
		"upload": uploadJSON(item.Upload),
	}
	if item.JobID != nil {
		j := map[string]any{
			"id":     item.JobID.String(),
			"status": derefOrEmpty(item.JobStatus),
		}
		if item.JobUpdatedAt != nil {
			j["updated_at"] = item.JobUpdatedAt.UTC().Format(time.RFC3339Nano)
		}
		row["processing_job"] = j
	} else {
		row["processing_job"] = nil
	}
	return row
}

func derefOrEmpty(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
