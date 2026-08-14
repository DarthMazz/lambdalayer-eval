/*
 * Phase 2: 「依存する側」の共有ライブラリ。libevaldep.so にリンクする。
 *
 * Phase 3 における libtesseract.so（libleptonica.so 等に依存する）に
 * 相当する位置づけ。ctypes からこれをロードしたとき、依存先まで含めて
 * 解決されるかを確認する。
 */

/* libevaldep.so 側で定義される */
extern int dep_multiply(int a, int b);
extern const char *dep_version(void);

#define LIBEVALMAIN_VERSION "libevalmain 1.0.0 (phase2)"

/*
 * 依存先の関数を実際に呼ぶ。
 * ロードに成功しただけでは依存が本当に解決されたとは言い切れないため、
 * 依存先の処理結果が返ることをもって実行時リンクの成立を示す。
 */
int compute(int a, int b) { return dep_multiply(a, b) + 1; }

const char *main_version(void) { return LIBEVALMAIN_VERSION; }

/* 依存先のバージョン文字列を中継して返す */
const char *dep_version_via_main(void) { return dep_version(); }
