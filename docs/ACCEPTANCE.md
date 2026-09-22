# Матрица приёмки T-01…T-80

Сверка с разделом 25 AGENT.md, 17.09.2026. Это карта **покрытия требований**, а не заявление, что 80 независимых приёмочных сценариев прошли. «Покрыт» означает наличие прямых проверок результата; «частично» — проверена лишь часть сценария или близкий случай; «не покрыт» — подходящего автоматического сценария не найдено. Наличие функции в рабочем коде само по себе не считается тестом. Итоги запусков приведены в REFACTOR_REPORT.md и отчётах эпиков.

Обозначения источников:

- **I** — [test_inventory_v1.py](../tests/integration/test_inventory_v1.py).
- **P** — [test_pipeline_v1.py](../tests/integration/test_pipeline_v1.py).
- **M** — [test_maintenance_v1.py](../tests/integration/test_maintenance_v1.py).
- **B** — [test_maintenance_postgres.py](../tests/integration/test_maintenance_postgres.py).
- **R** — [test_isolation_races.py](../tests/integration/test_isolation_races.py): чужие UUID и реальные PostgreSQL races.
- **Q** — [test_redis_recovery.py](../tests/integration/test_redis_recovery.py), реальный результат [redis-loss-evidence.json](redis-loss-evidence.json); **C** — [test_cooldown_v1.py](../tests/integration/test_cooldown_v1.py).
- **U** — [test_models_media.py](../tests/unit/test_models_media.py); **UM** — [test_maintenance_safety.py](../tests/unit/test_maintenance_safety.py).
- **UI** — компонентные проверки в [frontend/src/v1](../frontend/src/v1): Review.test.jsx, App.test.jsx, Settings.test.jsx, api.test.js, Reminders.test.jsx, AdminTools.test.jsx. Они используют mock API, это не браузерный E2E.
- **S** — [stack-smoke.json](stack-smoke.json): настоящие PostgreSQL, Redis/arq, MinIO, Qdrant, распознавание фотографии и голоса, HITL, подтверждение и поиск. **L** — [local-model-smoke.json](local-model-smoke.json): 3 фото, Ollama Gemma3:4b и BGE-M3. **A** — [audio-case-smoke.json](audio-case-smoke.json), [audio-endpoint-smoke.json](audio-endpoint-smoke.json): настоящий WAV и контрольная тишина через доверенный endpoint.

Большинство API-тестов использует SQLite. Настоящие PostgreSQL-проверки конкурентности и backup/restore запускаются отдельно по opt-in переменным; SQLite не доказывает семантику PostgreSQL row locks. `test_` в именах ниже сохранён, чтобы нужный тест можно было найти напрямую.

| ID | Проверяемое требование | Фактическое доказательство | Покрытие / оставшийся пробел |
|---|---|---|---|
| T-01 | AI не пишет учёт до confirm | P `test_pipeline_persists_review_and_releases_gpu`; S `before_confirmation_items=0` | Покрыт |
| T-02 | Повтор confirm не дублирует действие | I `test_no_write_before_confirm_and_replay`, `test_confirmation_dedupe_and_retry_uses_fencing` | Покрыт |
| T-03 | Новый transport key той же ревизии | I `test_confirmation_dedupe_and_retry_uses_fencing` проверяет оба ключа и один confirmation_id | Покрыт |
| T-04 | Тот же ключ с другим телом | I `test_confirmation_dedupe_and_retry_uses_fencing` → 409 | Покрыт |
| T-05 | Конкурирующий расход не делает минус | I `test_postgres_concurrent_confirmation_and_overspend`: два расхода 7 из 10, applied/conflict, остаток 3 | Покрыт PostgreSQL-тестом; нужен отдельный opt-in запуск |
| T-06 | Частичный перенос 3 из 10 | I `test_partial_move_and_atomic_failure` → 7/3 | Покрыт |
| T-07 | Ошибка группы откатывает всё | I `test_apply_crash_rolls_back_every_write_then_retries_once`, `test_partial_move_and_atomic_failure` | Покрыт |
| T-08 | Разные сроки остаются разными lots | [test_domain_acceptance.py](../tests/integration/test_domain_acceptance.py) `test_receipts_keep_medicine_expiries_and_individual_serials_separate` | Пройдено: два независимых поступления 10 и 20 таблеток создают одну карточку и две партии с разными сроками; суммарный остаток 30 |
| T-09 | Разные serial — отдельные individual | [test_domain_acceptance.py](../tests/integration/test_domain_acceptance.py) `test_receipts_keep_medicine_expiries_and_individual_serials_separate`; I `test_untracked_presence_and_individual_uniqueness` | Пройдено: одинаковое название, serial A/B и явный выбор отдельных предметов дают две карточки и два экземпляра по 1; дубликат и дробный перенос запрещены |
| T-10 | Unknown нельзя частично расходовать/перенести | [test_domain_acceptance.py](../tests/integration/test_domain_acceptance.py) `test_unknown_partial_move_rejected_then_set_eight_consume_two_with_history`; I `test_unknown_is_not_zero_and_only_moves_whole` | Пройдено: частичный перенос блокируется UNKNOWN_QUANTITY и confirm 409, исходный null и место сохранены; расход запрещён, whole-перенос сохраняет null |
| T-11 | Последний расход даёт depleted, сохраняя карточку и историю | M `test_last_unit_consumed_cancels_future_reminder_occurrences` | Покрыт |
| T-12 | Ноль + unknown не означает пустоту | I `test_archived_unknown_lot_does_not_count_as_current_presence` | Покрыт: unknown сохраняется до явного архивирования этой партии |
| T-13 | set_quantity и consume — разные команды и журнал | [test_domain_acceptance.py](../tests/integration/test_domain_acceptance.py) `test_unknown_partial_move_rejected_then_set_eight_consume_two_with_history` | Пройдено: unknown → set 8 → consume 2 даёт 6; разные операции, журнал null→8 с неизвестной дельтой и 8→6 с дельтой −2 tablet |
| T-14 | Нельзя отменить перенос поверх позднего расхода | [test_domain_acceptance.py](../tests/integration/test_domain_acceptance.py) `test_move_reversal_after_destination_consumption_preserves_stock_and_journal` | Пройдено: перенос 3 из 10, расход 2 в назначении, reverse блокируется REVERSE_CONFLICT/409; остатки 7+1 и исходный журнал переноса неизменны |
| T-15 | Нет догадки кг→таблетки | I `test_decimal_conversion_conservation_and_step` → INVALID_UNIT_CONVERSION | Покрыт |
| T-16 | Конкурирующие переносы мест не создают цикл | R `test_postgres_concurrent_location_moves_cannot_create_a_cycle` | Покрыт: реальный PostgreSQL, один перенос принят, дерево проверено обходом |
| T-17 | Полная форма подтверждается одним действием | P `test_pipeline_persists_review_and_releases_gpu`; S `can_confirm=true`; UI Review | Покрыт на API/компонентах; браузерный E2E не выполнялся |
| T-18 | Исправление 20→19 без нового ML | test_final_acceptance.py: test_ai_quantity_edit_twenty_to_nineteen_does_not_repeat_model | Покрыт: две исходные inference-попытки, inline confirm меняет 20 на 19; повторного вызова нет |
| T-19 | Два похожих предмета выбираются карточкой | test_final_acceptance.py: test_two_headphones_have_distinct_candidate_cards | Покрыт: два варианта наушников имеют различающиеся labels; выбор ID увеличивает только выбранную карточку |
| T-20 | Необязательный срок можно оставить неизвестным | I `test_no_write_before_confirm_and_replay` принимает поступление без даты | Покрыт |
| T-21 | Confirm несёт изменения при потерянном PATCH | I `test_unsaved_changes_and_stale_form`; UI Review отправляет changes вместе с confirm | Покрыт |
| T-22 | Старая форма сохраняет совместимые ручные правки | test_final_acceptance.py: test_stale_stock_review_preserves_multiple_inline_changes | Покрыт: конкурентный расход, inline quantity/reason сохранены в новой ревизии после 409; остаток меняется только после повторного confirm |
| T-23 | Изменение остатка перед apply даёт конфликт | I `test_changes_after_acceptance_produce_conflict_without_partial_write` | Покрыт |
| T-24 | Три расхода применяются одним batch | I `test_combined_confirmation_is_one_atomic_operation`; UI App объединение ревизий | Покрыт |
| T-25 | Отдельное подтверждение источника запрещает повтор batch | test_final_acceptance.py: test_separately_confirmed_source_blocks_combined_confirmation | Покрыт: отдельный расход меняет 10→8, combined confirm отклоняется 409 без второго расхода |
| T-26 | Без названия можно сохранить временную фотокарточку | M `test_unnamed_photo_can_be_confirmed_as_temporary_card`; I `test_temporary_item_name_is_frozen_across_review_confirm_and_apply` | Покрыт: карточка/фото появляются после confirm; системное имя неизменно между preview, revision, confirm, apply и replay со сдвигом времени |
| T-27 | Отрицание/будущий план требуют явного выбора | I `test_negated_intent_survives_patch_and_requires_operation_choice`, `test_combining_does_not_bypass_intent_choice`; U `test_model_uuid_and_schedule_are_untrusted` | Покрыт |
| T-28 | Неподдерживаемый таймер не исчезает молча | I `test_timer_requires_explicit_inventory_only_choice`; UI Review отдельное решение | Покрыт |
| T-29 | Три фото превращаются в один image input | U `test_single_image_boundary_and_no_sdk_retry`; L `image_count=3`, `image_inputs_per_call=1` | Покрыт, включая реальную модель |
| T-30 | EXIF и обратное crop/source соответствие | U `test_collage_orientation_coordinates_and_source_order` | Покрыт |
| T-31 | Мелкий текст: unknown без выдуманной даты | test_image_limits.py; small-label-before-guard.json; small-label-smoke.json | Покрыт конкретным реальным снимком: модель ошиблась, защитная нормализация small_tile оставила unknown; автоматический detail-pass не заявляется |
| T-32 | Неверный MIME/слишком много pixels отклоняется | U `test_media_rejects_mime_and_decompression_limit` | Покрыт |
| T-33 | Длинное аудио сегментируется | U `test_audio_normalization_segments_and_overlap`; P `test_long_audio_has_retry_budget_per_segment` | Покрыт; настоящий длинный WAV через endpoint отдельно не прогонялся |
| T-34 | Audio/image идут раздельными стадиями | S: реальный голос+фото, 3 попытки; L audio unsupported; A audio-only | Покрыт реальной связкой адаптеров |
| T-35 | Повреждённый JSON: ограниченные попытки и ручная форма | P `test_malformed_model_json_stops_at_stage_budget` | Покрыт на границе адаптера: INVALID_MODEL_JSON исчерпывает stage budget и создаёт ручную форму; сырой повреждённый HTTP-body здесь не разбирается |
| T-36 | Выдуманный UUID отклоняется | U `test_model_uuid_and_schedule_are_untrusted` → UNKNOWN_MODEL_CANDIDATE | Покрыт |
| T-37 | Порядок фото меняет manifest/cache key | U `test_collage_orientation_coordinates_and_source_order` | Покрыт |
| T-38 | Инструкция на фото не исполняется как команда | P `test_image_instruction_cannot_execute_or_choose_unsupplied_uuid` | Покрыт на API/pipeline с нарисованной инструкцией и враждебным mock-ответом; это не оценка устойчивости самой реальной модели |
| T-39 | force_local не уходит наружу при ошибке | test_privacy_acceptance.py: test_force_local_model_errors_never_call_cloud | Покрыт целым pipeline: разрешённый cloud, локальные ошибки, исчерпание бюджета, ручная форма, ноль external calls |
| T-40 | Privacy uncertain остаётся локальной | U `test_restrictive_privacy_wins` | Покрыт на чистой функции политики; сетевой integration кейс отсутствует |
| T-41 | Private-кандидат не включается во внешний payload | test_privacy_acceptance.py: test_private_candidate_alone_prevents_external_payload | Покрыт: найден private-кандидат, весь pipeline остаётся локальным; внешний адаптер запрещён assertion |
| T-42 | Один private источник делает весь коллаж private | test_privacy_acceptance.py: test_private_candidate_and_mixed_photo_sources_block_cloud | Покрыт: загружены три фото с разными policy; collage local_only, внешних вызовов нет |
| T-43 | Срочный cloud-off блокирует следующий вызов | P `test_urgent_cloud_block_is_rechecked_before_http` | Покрыт: запрет установлен между предварительной и последней проверкой; вызов cloud запрещён assertion |
| T-44 | Чужие UUID media/task/proposal недоступны | R `test_known_foreign_uuids_do_not_expose_media_task_or_proposal`, `test_known_foreign_uuids_cannot_be_modified_or_attached` | Покрыт: read/download/poll/confirm/retry/replay/attachment, чужие записи не изменились |
| T-45 | Нельзя повысить app_role через профиль | P `test_auth_profile_cannot_elevate_and_refresh_replay_revokes` | Покрыт |
| T-46 | Диагностика не раскрывает секреты | test_privacy_acceptance.py: test_model_errors_do_not_expose_secrets_in_trace_or_logs | Покрыт: secret marker в исключении модели отсутствует в task/trace/логах; verbose raw payload недоступен |
| T-47 | Удалённый private point скрыт при отставшем Qdrant | P `test_stale_search_hits_are_filtered_by_postgres` | Покрыт: mock-поиск возвращает deleted/foreign/несуществующий/живой UUID, SQL hydration отдаёт только живой; fixture использует SQLite |
| T-48 | Document нельзя сделать cloud_allowed | test_final_acceptance.py: test_document_cannot_be_changed_to_cloud_allowed | Покрыт API: update_item получает POLICY_RESTRICTED, подтверждённый документ остаётся local_only |
| T-49 | Повтор после domain commit возвращает прежний результат | [test_runtime_acceptance.py](../tests/integration/test_runtime_acceptance.py) `test_worker_loss_after_commit_replays_saved_result_after_lease_expiry` | Покрыт на границе commit/ack: BaseException оставляет lease/outbox, после expiry и reconcile повтор возвращает тот же result и одну операцию; физический kill процесса не выполнялся |
| T-50 | Утрата Redis восстанавливает durable jobs | Q `test_real_redis_loss_recovers_postgres_confirmation_exactly_once`; P `test_reconcile_without_redis_state_and_cpu_pause` | Покрыт: настоящий FLUSHDB, PostgreSQL confirmation восстановлен reconciler и применён arq; поздняя доставка/HTTP replay оставляют одну операцию, карточку и количество 3 |
| T-51 | Ожидание пользователя не удерживает GPU | test_privacy_acceptance.py: test_review_survives_a_day_without_holding_gpu | Покрыт: времена задачи сдвинуты на сутки, reconcile сохраняет review/hash, GPU остаётся idle |
| T-52 | Поздняя попытка отклоняется fencing | P `test_late_result_after_cancel_is_fenced` | Покрыт |
| T-53 | Одновременные cancel/confirm согласованы | R `test_postgres_cancel_and_confirm_have_one_consistent_outcome` | Покрыт: два порядка запуска настоящих конкурентных PostgreSQL/HTTP-запросов |
| T-54 | Физически живой запрос не освобождает GPU | P `test_late_result_after_cancel_is_fenced`, `test_unknown_timeout_quarantines_and_creates_manual_form`, `test_expired_gpu_lease_is_not_treated_as_idle` | Покрыт с управляемым mock inference |
| T-55 | Snapshot не меняется, urgent запреты учитываются | P `test_model_route_snapshot_change_requires_new_intent`, `test_urgent_cloud_block_is_rechecked_before_http` | Покрыт для model route и срочного cloud запрета; воспроизводимость всех числовых параметров отдельно не перебиралась |
| T-56 | Неверные heartbeat/lease отклоняются | U `test_setting_invariants` | Покрыт |
| T-57 | Требующий restart набор остаётся pending | P `test_settings_restart_history_rollback`; UI Settings путь validate/apply | Частично: backend pending/effective проверен; UI pending-status отдельно не утверждается тестом |
| T-58 | Rollback создаёт ревизию и сохраняет историю | test_final_acceptance.py: test_settings_rollback_preserves_old_history_payloads | Покрыт: новая ревизия 3, старые JSON истории полностью неизменны, значения совпадают с целевой ревизией 1 |
| T-59 | Ошибка Qdrant повторяет outbox без отката каталога | [test_runtime_acceptance.py](../tests/integration/test_runtime_acceptance.py) `test_qdrant_failure_after_commit_retries_without_losing_catalog` | Покрыт: mock Qdrant upsert падает после подтверждённого поступления; каталог/история сохранены, pending outbox повторён reconciler, индекс догнал ревизию |
| T-60 | Старое index event не затирает новое | P `test_old_outbox_event_cannot_overwrite_new_search_document` | Покрыт с mock Qdrant: после событий 2→1 обе записи содержат актуальные текст и revision=2 |
| T-61 | Minute 429 не становится daily block | C `test_minute_cooldown_tracks_actual_attempt_after_deployment_change`; U `test_provider_errors` | Покрыт: настоящий адаптер с mock HTTP 429 сохраняет Retry-After=45 для Attempt.model_id, retry_wait совпадает со сроком; новый deployment работает до его истечения |
| T-62 | Pacific midnight учитывает DST | U `test_daily_quota_reset_observes_pacific_dst` (январь/июль) | Покрыт |
| T-63 | SDK+worker не превышают общий бюджет | [test_runtime_acceptance.py](../tests/integration/test_runtime_acceptance.py) `test_adapter_and_worker_retries_share_one_total_attempt_budget` | Покрыт: настоящий LocalAdapter с mock HTTP даёт ошибку/ошибку/gate/ошибку; ровно 4 HTTP и Attempt на двух стадиях, общий лимит достигнут, повтор dispatch не вызывает модель |
| T-64 | Много задач используют пакетный polling | test_final_acceptance.py: test_many_tasks_use_one_status_request | Покрыт backend: 30 задач одним status request, затем все unchanged; будущий клиент вне текущего эпика |
| T-65 | Месяц сохраняет точность и явное правило | I `test_month_precision_expiry_requires_explicit_policy`, `test_changed_expiry_policy_requires_a_new_review` | Покрыт |
| T-66 | Открытие сокращает expiry и меняет occurrences | [test_runtime_acceptance.py](../tests/integration/test_runtime_acceptance.py) `test_opening_shortens_expiry_and_replaces_reminder_generation` | Покрыт: подтверждённое вскрытие сокращает срок до 27.09, отменяет старое поколение и доставляет только новое напоминание 20.09 |
| T-67 | Последний расход отменяет будущие напоминания | M `test_last_unit_consumed_cancels_future_reminder_occurrences` | Покрыт |
| T-68 | Untracked документ получает напоминание | M `test_untracked_document_gets_expiry_notification_without_numeric_quantity` | Покрыт: quantity=null/not_applicable, подтверждённый документ присутствует в inbox по сроку |
| T-69 | Два быстрых изменения срока дают актуальное поколение | M `test_two_expiry_updates_only_deliver_the_current_generation` | Покрыт: две отменённые occurrences, одна актуальная доставлена |
| T-70 | Catch-up объединяет старые пороги | M `test_reminders_unknown_depleted_inclusive_expiry_and_snooze` (30/7/0 одновременно просрочены) | Покрыт |
| T-71 | Повтор доставки даёт одну in-app запись | M `test_reminders_unknown_depleted_inclusive_expiry_and_snooze` вызывает planner повторно | Покрыт для in-app; внешняя доставка не включена |
| T-72 | Укорочение retention требует точного impact и подтверждения | M `test_retention_dry_run_counts_only_newly_eligible_rows_and_requires_confirmation` | Покрыт |
| T-73 | Shared bytes живут после удаления одной ссылки | M `test_shared_bytes_survive_first_purge`, `test_shared_media_blocked_when_last_live_reference_is_deleted` | Покрыт |
| T-74 | Старая копия не воскрешает удалённое | B `test_real_backup_restore_reapplies_newer_deletion_ledger` | Покрыт настоящими pg_dump/pg_restore и актуальным ledger |
| T-75 | Выключенный dataset не получает исправления | UM `test_unavailable_extensions_are_not_silently_enabled`; dataset writer не поставляется | Покрыт ограничением поставки: включение запрещено, отдельное копирование отсутствует |
| T-76 | CSV-имя с «=» не исполняется формулой | M `test_export_confirmed_snapshot_zip_checksums_and_csv_formula`; UM `test_csv_neutralizes_spreadsheet_commands` | Покрыт |
| T-77 | Учёт аптечки не создаёт график приёма | [test_runtime_acceptance.py](../tests/integration/test_runtime_acceptance.py) `test_medicine_receipt_and_consumption_never_create_dosing_schedule` | Покрыт API/БД: лекарство с дозировкой принято и списано 10→8; dosing rule отклонён 422, таблиц графика нет, единственная occurrence относится к expiry, утренних/вечерних уведомлений нет |
| T-78 | Audio TTL сохраняет подтверждённый учёт/историю | M `test_audio_retention_removes_input_but_keeps_confirmed_catalog_and_history` | Покрыт: audio bytes/binding/транскрипт удалены, известный остаток и JSON истории неизменны |
| T-79 | Unknown→known того же lot не теряет число | I `test_unknown_move_to_known_same_lot_requires_explicit_resolution` | Покрыт: известные 5 сохранены при отказе; после явного set 2 и переноса получается 7 |
| T-80 | Retry apply сохраняет идентичность намерения | I `test_apply_crash_rolls_back_every_write_then_retries_once`, `test_confirmation_dedupe_and_retry_uses_fencing` | Покрыт |

## Границы финальной проверки 21.09.2026

Общий прогон: **186 passed**, включая настоящие PostgreSQL/Redis/backup проверки. Дополнительные модули: [предметные сценарии](../tests/integration/test_domain_acceptance.py), [runtime](../tests/integration/test_runtime_acceptance.py), [privacy](../tests/integration/test_privacy_acceptance.py), [итоговая приёмка](../tests/integration/test_final_acceptance.py), [медиа/прогресс](../tests/integration/test_media_catalog.py), [пары](../tests/integration/test_pairs.py), [пределы и память изображений](../tests/unit/test_image_limits.py).

T-22 и T-58 закрыты прямыми проверками сохранения нескольких правок при конфликте и неизменяемой истории rollback. UI-аспект T-57 исключён из текущего эпика по указанию владельца; backend pending/effective проверен. Физический kill процесса после commit не выполнялся — T-49 проверяет ту же границу управляемым BaseException. Это не оценка всех вариантов аппаратного сбоя.

Реальные smoke подтверждают работоспособность конкретных кейсов, не точность всех полей всего личного набора. Для T-31 показана и исходная ошибка Gemma, и безопасное unknown после нормализации. Полная калибровка и автоматические detail-pass требуют отдельной проверки.
