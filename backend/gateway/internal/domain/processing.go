package domain

// Статусы processing_jobs.status — синхронизировать с internal/migrate/migrations/schema.sql.
//
// Типичный порядок пайплайна: queued → running → stt → llm → render_audio → done | failed.
// Дополнительно допустим cancelled (резерв; в runner пока не выставляется).
const (
	JobQueued        = "queued"
	JobRunning       = "running"
	JobSTT           = "stt"
	JobLLM           = "llm"
	JobRenderAudio   = "render_audio"
	JobDone          = "done"
	JobFailed        = "failed"
	JobCancelled   = "cancelled"
)

// Типы сущностей для llm_entities[].entity_type (рекомендация для контракта с Llama).
const (
	EntityPassport = "passport"
	EntityINN      = "inn"
	EntitySNILS    = "snils"
	EntityPhone    = "phone"
	EntityEmail    = "email"
	EntityAddress  = "address"
)
