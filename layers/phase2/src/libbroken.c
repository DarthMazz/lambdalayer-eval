/*
 * Phase 2 / 検証項目 2-3 用。
 *
 * libmissing.so にリンクしてビルドするが、libmissing.so は Layer に
 * 同梱しない。依存 .so が欠けている場合に ctypes がどのようなエラーを
 * 返すかを実測し、Phase 3 で依存の洗い出しに漏れがあった場合の
 * 切り分け材料とする。
 */

extern int missing_fn(void);

int broken_entry(void) { return missing_fn(); }
