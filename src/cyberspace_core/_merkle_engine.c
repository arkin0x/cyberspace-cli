/*
 * _merkle_engine.c — Fast Merkle tree computation for Cyberspace sidestep proofs.
 *
 * Provides:
 *   compute_subtree_root(base: int, height: int) -> bytes
 *   compute_subtree_root_with_proof(base: int, height: int) -> (bytes, list[bytes])
 *
 * Leaf hash:  SHA256(SIDESTEP_DOMAIN || int_to_bytes_be_min(value))
 * Internal:   SHA256(left || right)
 *
 * Uses stack-based streaming: O(h) memory, not O(2^h).
 * Self-contained SHA256 (no OpenSSL dependency).
 *
 * Build:
 *   gcc -O3 -shared -fPIC \
 *       -I$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))") \
 *       -o _merkle_engine$(python3-config --extension-suffix) _merkle_engine.c
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#include <stdint.h>

/* ================================================================== */
/* Standalone SHA-256 implementation (public domain / RFC 6234 style)  */
/* ================================================================== */

typedef struct {
    uint32_t state[8];
    uint64_t count;
    unsigned char buffer[64];
} SHA256_CTX_OURS;

static const uint32_t K256[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};

#define ROR32(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x,y,z)   (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x,y,z)  (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x)       (ROR32(x,2)  ^ ROR32(x,13) ^ ROR32(x,22))
#define EP1(x)       (ROR32(x,6)  ^ ROR32(x,11) ^ ROR32(x,25))
#define SIG0(x)      (ROR32(x,7)  ^ ROR32(x,18) ^ ((x) >> 3))
#define SIG1(x)      (ROR32(x,17) ^ ROR32(x,19) ^ ((x) >> 10))

static void sha256_transform(uint32_t state[8], const unsigned char block[64])
{
    uint32_t W[64], a, b, c, d, e, f, g, h, t1, t2;
    int i;
    for (i = 0; i < 16; i++)
        W[i] = ((uint32_t)block[i*4]<<24) | ((uint32_t)block[i*4+1]<<16) |
               ((uint32_t)block[i*4+2]<<8) | (uint32_t)block[i*4+3];
    for (i = 16; i < 64; i++)
        W[i] = SIG1(W[i-2]) + W[i-7] + SIG0(W[i-15]) + W[i-16];

    a=state[0]; b=state[1]; c=state[2]; d=state[3];
    e=state[4]; f=state[5]; g=state[6]; h=state[7];

    for (i = 0; i < 64; i++) {
        t1 = h + EP1(e) + CH(e,f,g) + K256[i] + W[i];
        t2 = EP0(a) + MAJ(a,b,c);
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    state[0]+=a; state[1]+=b; state[2]+=c; state[3]+=d;
    state[4]+=e; state[5]+=f; state[6]+=g; state[7]+=h;
}

static void sha256_init(SHA256_CTX_OURS *ctx) {
    ctx->state[0]=0x6a09e667; ctx->state[1]=0xbb67ae85;
    ctx->state[2]=0x3c6ef372; ctx->state[3]=0xa54ff53a;
    ctx->state[4]=0x510e527f; ctx->state[5]=0x9b05688c;
    ctx->state[6]=0x1f83d9ab; ctx->state[7]=0x5be0cd19;
    ctx->count = 0;
    memset(ctx->buffer, 0, 64);
}

static void sha256_update(SHA256_CTX_OURS *ctx, const unsigned char *data, size_t len) {
    size_t i, idx = (size_t)(ctx->count & 63);
    ctx->count += len;
    for (i = 0; i < len; i++) {
        ctx->buffer[idx++] = data[i];
        if (idx == 64) {
            sha256_transform(ctx->state, ctx->buffer);
            idx = 0;
        }
    }
}

static void sha256_final(SHA256_CTX_OURS *ctx, unsigned char hash[32]) {
    size_t idx = (size_t)(ctx->count & 63);
    ctx->buffer[idx++] = 0x80;
    if (idx > 56) {
        memset(ctx->buffer + idx, 0, 64 - idx);
        sha256_transform(ctx->state, ctx->buffer);
        idx = 0;
    }
    memset(ctx->buffer + idx, 0, 56 - idx);
    uint64_t bits = ctx->count * 8;
    for (int i = 0; i < 8; i++)
        ctx->buffer[56 + i] = (unsigned char)(bits >> (56 - 8*i));
    sha256_transform(ctx->state, ctx->buffer);
    for (int i = 0; i < 8; i++) {
        hash[i*4]   = (unsigned char)(ctx->state[i] >> 24);
        hash[i*4+1] = (unsigned char)(ctx->state[i] >> 16);
        hash[i*4+2] = (unsigned char)(ctx->state[i] >> 8);
        hash[i*4+3] = (unsigned char)(ctx->state[i]);
    }
}

/* Convenience: SHA256(data, len) -> hash[32] */
static void sha256_oneshot(const unsigned char *data, size_t len, unsigned char *hash) {
    SHA256_CTX_OURS ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, data, len);
    sha256_final(&ctx, hash);
}

/* ================================================================== */
/* End of standalone SHA-256                                           */
/* ================================================================== */

/* Domain separation prefix for leaf hashes. */
static const unsigned char SIDESTEP_DOMAIN[] = "CYBERSPACE_SIDESTEP_V1";
#define SIDESTEP_DOMAIN_LEN 22

#define HASH_SIZE 32
#define MAX_HEIGHT 64  /* supports up to 2^64 leaves */

/* ------------------------------------------------------------------ */
/* int_to_bytes_be_min: convert a Python int to minimal big-endian    */
/* bytes, matching Python's n.to_bytes((n.bit_length()+7)//8, 'big')  */
/* For n==0, returns a single 0x00 byte.                              */
/* Returns number of bytes written, or -1 on error.                   */
/* buf must be at least 'bufsize' bytes.                              */
/* ------------------------------------------------------------------ */

static int
int_to_bytes_be_min(PyObject *n, unsigned char *buf, int bufsize)
{
    /* Fast path: fits in unsigned long long */
    int overflow = 0;
    unsigned long long val = PyLong_AsUnsignedLongLongMask(n);

    /* Check if the value actually fits in ULL and is non-negative */
    if (!PyErr_Occurred()) {
        /* Verify it round-trips (handles negative and overflow) */
        PyObject *reconstructed = PyLong_FromUnsignedLongLong(val);
        if (reconstructed) {
            int cmp = PyObject_RichCompareBool(n, reconstructed, Py_EQ);
            Py_DECREF(reconstructed);
            if (cmp == 1) {
                /* Fits in ULL — fast path */
                if (val == 0) {
                    buf[0] = 0;
                    return 1;
                }
                int nbytes = 0;
                unsigned long long tmp = val;
                while (tmp > 0) {
                    nbytes++;
                    tmp >>= 8;
                }
                if (nbytes > bufsize) return -1;
                for (int i = nbytes - 1; i >= 0; i--) {
                    buf[i] = (unsigned char)(val & 0xFF);
                    val >>= 8;
                }
                return nbytes;
            }
        }
    }
    PyErr_Clear();

    /* Slow path: arbitrary precision via Python's to_bytes */
    PyObject *bit_length_result = PyObject_CallMethod(n, "bit_length", NULL);
    if (!bit_length_result) return -1;

    long bit_length = PyLong_AsLong(bit_length_result);
    Py_DECREF(bit_length_result);
    if (bit_length < 0 && PyErr_Occurred()) return -1;

    if (bit_length == 0) {
        buf[0] = 0;
        return 1;
    }

    int nbytes = (int)((bit_length + 7) / 8);
    if (nbytes > bufsize) {
        PyErr_SetString(PyExc_OverflowError, "integer too large for buffer");
        return -1;
    }

    PyObject *py_nbytes = PyLong_FromLong(nbytes);
    PyObject *py_big = PyUnicode_FromString("big");
    PyObject *bytes_obj = PyObject_CallMethod(n, "to_bytes", "OO", py_nbytes, py_big);
    Py_DECREF(py_nbytes);
    Py_DECREF(py_big);
    if (!bytes_obj) return -1;

    char *ptr;
    Py_ssize_t len;
    if (PyBytes_AsStringAndSize(bytes_obj, &ptr, &len) < 0) {
        Py_DECREF(bytes_obj);
        return -1;
    }
    memcpy(buf, ptr, len);
    Py_DECREF(bytes_obj);
    return (int)len;
}

/* ------------------------------------------------------------------ */
/* Compute leaf hash: SHA256(SIDESTEP_DOMAIN || int_to_bytes_be_min(value)) */
/* ------------------------------------------------------------------ */

static int
compute_leaf_hash(PyObject *value, unsigned char *out)
{
    unsigned char valbuf[64];  /* enough for up to 512-bit integers */
    int vlen = int_to_bytes_be_min(value, valbuf, sizeof(valbuf));
    if (vlen < 0) return -1;

    SHA256_CTX_OURS ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, SIDESTEP_DOMAIN, SIDESTEP_DOMAIN_LEN);
    sha256_update(&ctx, valbuf, vlen);
    sha256_final(&ctx, out);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Compute leaf hash from ULL value (fast path, no Python objects)    */
/* ------------------------------------------------------------------ */

static void
compute_leaf_hash_ull(unsigned long long val, unsigned char *out)
{
    unsigned char valbuf[8];
    int nbytes;

    if (val == 0) {
        nbytes = 1;
        valbuf[0] = 0;
    } else {
        nbytes = 0;
        unsigned long long tmp = val;
        while (tmp > 0) { nbytes++; tmp >>= 8; }
        unsigned long long v = val;
        for (int i = nbytes - 1; i >= 0; i--) {
            valbuf[i] = (unsigned char)(v & 0xFF);
            v >>= 8;
        }
    }

    SHA256_CTX_OURS ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, SIDESTEP_DOMAIN, SIDESTEP_DOMAIN_LEN);
    sha256_update(&ctx, valbuf, nbytes);
    sha256_final(&ctx, out);
}

/* ------------------------------------------------------------------ */
/* Compute parent hash: SHA256(left || right)                         */
/* ------------------------------------------------------------------ */

static void
compute_parent_hash(const unsigned char *left, const unsigned char *right,
                    unsigned char *out)
{
    SHA256_CTX_OURS ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, left, HASH_SIZE);
    sha256_update(&ctx, right, HASH_SIZE);
    sha256_final(&ctx, out);
}

/* ------------------------------------------------------------------ */
/* Stack-based streaming Merkle root computation.                     */
/* O(h) memory. Processes leaves in order [base, base + 2^height).   */
/*                                                                    */
/* If proof_siblings != NULL, collects inclusion proof for leaf 0.    */
/* ------------------------------------------------------------------ */

static PyObject *
_compute_subtree(PyObject *py_base, int height, int collect_proof)
{
    if (height < 0 || height > MAX_HEIGHT) {
        PyErr_Format(PyExc_ValueError, "height must be in [0, %d], got %d",
                     MAX_HEIGHT, height);
        return NULL;
    }

    /* Height 0: single leaf */
    if (height == 0) {
        unsigned char root[HASH_SIZE];
        if (compute_leaf_hash(py_base, root) < 0)
            return NULL;
        PyObject *root_bytes = PyBytes_FromStringAndSize((char *)root, HASH_SIZE);
        if (!collect_proof)
            return root_bytes;
        PyObject *proof_list = PyList_New(0);
        if (!proof_list) { Py_DECREF(root_bytes); return NULL; }
        PyObject *result = PyTuple_Pack(2, root_bytes, proof_list);
        Py_DECREF(root_bytes);
        Py_DECREF(proof_list);
        return result;
    }

    /* Try to use ULL fast path */
    int use_ull = 0;
    unsigned long long base_ull = 0;
    unsigned long long leaf_count = (unsigned long long)1 << height;

    /* Check: can base + leaf_count - 1 fit in ULL? */
    {
        int overflow = 0;
        unsigned long long bv = PyLong_AsUnsignedLongLong(py_base);
        if (bv == (unsigned long long)-1 && PyErr_Occurred()) {
            PyErr_Clear();
            use_ull = 0;
        } else {
            /* Check overflow: base_ull + leaf_count - 1 must not overflow */
            if (height < 64 && bv <= ULLONG_MAX - leaf_count + 1) {
                use_ull = 1;
                base_ull = bv;
            }
        }
    }

    /* Stack: stack_hash[i] holds the hash at level i, valid if stack_valid[i] */
    unsigned char stack_hash[MAX_HEIGHT + 1][HASH_SIZE];
    int stack_valid[MAX_HEIGHT + 1];
    memset(stack_valid, 0, sizeof(stack_valid));

    /* Inclusion proof siblings for leaf 0 */
    unsigned char proof[MAX_HEIGHT][HASH_SIZE];
    int proof_collected = 0;  /* how many levels collected so far */

    /* Process each leaf */
    unsigned long long count = leaf_count;
    for (unsigned long long i = 0; i < count; i++) {
        unsigned char current[HASH_SIZE];

        if (use_ull) {
            compute_leaf_hash_ull(base_ull + i, current);
        } else {
            PyObject *idx = PyLong_FromUnsignedLongLong(i);
            if (!idx) return NULL;
            PyObject *val = PyNumber_Add(py_base, idx);
            Py_DECREF(idx);
            if (!val) return NULL;
            if (compute_leaf_hash(val, current) < 0) {
                Py_DECREF(val);
                return NULL;
            }
            Py_DECREF(val);
        }

        int level = 0;
        while (stack_valid[level]) {
            /* Collect proof: leaf 0 is always on leftmost path.
             * At each level, leaf 0's ancestor is always the left child.
             * The sibling (right child) is `current`. */
            if (collect_proof && proof_collected == level) {
                memcpy(proof[proof_collected], current, HASH_SIZE);
                proof_collected++;
            }
            compute_parent_hash(stack_hash[level], current, current);
            stack_valid[level] = 0;
            level++;
        }
        memcpy(stack_hash[level], current, HASH_SIZE);
        stack_valid[level] = 1;
    }

    /* The root should be at stack_hash[height] */
    unsigned char *root = stack_hash[height];

    PyObject *root_bytes = PyBytes_FromStringAndSize((char *)root, HASH_SIZE);
    if (!root_bytes) return NULL;

    if (!collect_proof)
        return root_bytes;

    /* Build proof list */
    PyObject *proof_list = PyList_New(height);
    if (!proof_list) { Py_DECREF(root_bytes); return NULL; }
    for (int i = 0; i < height; i++) {
        PyObject *h = PyBytes_FromStringAndSize((char *)proof[i], HASH_SIZE);
        if (!h) {
            Py_DECREF(root_bytes);
            Py_DECREF(proof_list);
            return NULL;
        }
        PyList_SET_ITEM(proof_list, i, h);  /* steals ref */
    }

    PyObject *result = PyTuple_Pack(2, root_bytes, proof_list);
    Py_DECREF(root_bytes);
    Py_DECREF(proof_list);
    return result;
}

/* ------------------------------------------------------------------ */
/* Python-facing functions                                            */
/* ------------------------------------------------------------------ */

static PyObject *
py_compute_subtree_root(PyObject *self, PyObject *args)
{
    PyObject *py_base;
    int height;

    if (!PyArg_ParseTuple(args, "Oi", &py_base, &height))
        return NULL;

    if (!PyLong_Check(py_base)) {
        PyErr_SetString(PyExc_TypeError, "base must be an integer");
        return NULL;
    }

    return _compute_subtree(py_base, height, 0);
}

static PyObject *
py_compute_subtree_root_with_proof(PyObject *self, PyObject *args)
{
    PyObject *py_base;
    int height;

    if (!PyArg_ParseTuple(args, "Oi", &py_base, &height))
        return NULL;

    if (!PyLong_Check(py_base)) {
        PyErr_SetString(PyExc_TypeError, "base must be an integer");
        return NULL;
    }

    return _compute_subtree(py_base, height, 1);
}

/* ------------------------------------------------------------------ */
/* Module definition                                                  */
/* ------------------------------------------------------------------ */

static PyMethodDef MerkleEngineMethods[] = {
    {"compute_subtree_root", py_compute_subtree_root, METH_VARARGS,
     "compute_subtree_root(base, height) -> bytes\n\n"
     "Compute the Merkle root for an aligned subtree starting at base\n"
     "with 2^height leaves. Returns a 32-byte SHA256 hash."},
    {"compute_subtree_root_with_proof", py_compute_subtree_root_with_proof,
     METH_VARARGS,
     "compute_subtree_root_with_proof(base, height) -> (bytes, list[bytes])\n\n"
     "Compute the Merkle root and inclusion proof for leaf 0."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef merkle_engine_module = {
    PyModuleDef_HEAD_INIT,
    "_merkle_engine",
    "Fast Merkle tree computation for Cyberspace sidestep proofs.",
    -1,
    MerkleEngineMethods
};

PyMODINIT_FUNC
PyInit__merkle_engine(void)
{
    return PyModule_Create(&merkle_engine_module);
}
