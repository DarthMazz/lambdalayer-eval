/*
 * Phase 2 / 検証項目 2-3 用。
 *
 * libbroken.so のリンク時にのみ使用し、Layer には同梱しない。
 * これにより libbroken.so は「DT_NEEDED に記録されているが実体が存在しない
 * 依存を持つライブラリ」となり、依存解決失敗時のエラーを観測できる。
 */

int missing_fn(void) { return 42; }
