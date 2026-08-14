/*
 * Phase 1: 外部依存を一切持たない検証用の共有ライブラリ。
 *
 * 「Lambda Layer に配置したネイティブモジュールを Python から呼べるか」を
 * 最小構成で確かめることだけを目的としている。依存を持たないことで、
 * 失敗した場合の原因を「Layer の配置とロードの仕組み」に限定できる。
 */

#define LIBEVAL_VERSION "libeval 1.0.0 (phase1)"

/* 基本的な呼び出しと戻り値の確認用 */
int add(int a, int b) { return a + b; }

/*
 * ポインタ返却の確認用。
 * Python 側で restype を c_char_p に宣言しないと、戻り値が既定の int(32bit)
 * として扱われ 64bit ポインタが切り詰められる。handler.py ではこの挙動も
 * 意図的に観測している。
 */
const char *version(void) { return LIBEVAL_VERSION; }
