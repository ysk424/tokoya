// Phase 7A-2 Step 2: standalone diagnostic probe (NOT linked into the
// Blender extension). Outside the extension runtime / SolverInterface
// entirely; each invocation is a fresh OS process with a fresh CUDA
// context, so a crash here cannot take Blender down with it.
//
// Goal: disambiguate which 0-byte CUDA allocation in PhysX 5.6.1 PBD
// cloth-buffer path is firing in our 4000 anchor + 4000 child + 4000
// spring configuration.
//
// CLI:
//   arm_a_b_probe.exe --arm=A|B --stage=1|2|3 [--max-tri=N] [--anchors=N]
//
// Arm A: helper->addCloth(...) called once with numTriangles=0,
//        partitionSprings() called.
// Arm B: addCloth NOT called, partitionSprings NOT called; the
//        PxPartitionedParticleCloth used by Stage 2 is the default
//        zero-initialised struct (nbCloths=0, nbPartitions=0, ...).
//
// Stage 1: build descriptor data, print every count we care about, exit.
//          No PxCreateAndPopulateParticleClothBuffer call. No simulate.
//          Safe even if the cloth path is fundamentally broken.
// Stage 2: also call PxCreateAndPopulateParticleClothBuffer +
//          addParticleBuffer. This is where the device-side
//          cuMemAlloc(0) crash should fire if the descriptor is bad.
// Stage 3: also call simulate(dt) + fetchResults + memcpyDtoH readback.
//          Only meaningful if Stage 2 succeeded.
//
// Output is line-based (prefixed [TAG]) so the wrapper script can grep
// for the last successful line before any crash.
#include <PxPhysicsAPI.h>
#include <extensions/PxParticleExt.h>
#include <cudamanager/PxCudaContextManager.h>
#include <cudamanager/PxCudaContext.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace physx;

static PxDefaultAllocator       gAllocator;
static PxDefaultErrorCallback   gErrCallback;

static void LOG(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    std::vfprintf(stdout, fmt, ap);
    std::fputc('\n', stdout);
    std::fflush(stdout);
    va_end(ap);
}

int main(int argc, char** argv) {
    // --- Parse CLI ---
    std::string arm = "A";
    int          stage          = 1;
    unsigned int max_triangles  = 1000u;
    unsigned int anchor_count   = 4000u;
    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];
        if (std::strncmp(a, "--arm=", 6) == 0)         arm = a + 6;
        else if (std::strncmp(a, "--stage=", 8) == 0)  stage = std::atoi(a + 8);
        else if (std::strncmp(a, "--max-tri=", 10) == 0) max_triangles = (unsigned)std::atoi(a + 10);
        else if (std::strncmp(a, "--anchors=", 10) == 0) anchor_count  = (unsigned)std::atoi(a + 10);
    }
    const bool armA = (arm == "A" || arm == "a");
    const unsigned int particle_count = anchor_count * 2u;

    LOG("[CONFIG] arm=%s stage=%d anchors=%u particles=%u max_triangles=%u",
        arm.c_str(), stage, anchor_count, particle_count, max_triangles);

    // --- Foundation + CUDA context ---
    PxFoundation* fnd = PxCreateFoundation(PX_PHYSICS_VERSION, gAllocator, gErrCallback);
    if (!fnd) { LOG("[FATAL] PxCreateFoundation"); return 10; }

    PxCudaContextManagerDesc cudaDesc;
    PxCudaContextManager* ctx = PxCreateCudaContextManager(*fnd, cudaDesc);
    if (!ctx || !ctx->contextIsValid()) {
        LOG("[FATAL] PxCreateCudaContextManager ptr=%p valid=%d",
            (void*)ctx, ctx ? (ctx->contextIsValid() ? 1 : 0) : -1);
        if (ctx) ctx->release();
        fnd->release();
        return 11;
    }
    LOG("[CUDA_OK] device=%s", ctx->getDeviceName() ? ctx->getDeviceName() : "(unknown)");

    PxPhysics* phy = PxCreatePhysics(PX_PHYSICS_VERSION, *fnd, PxTolerancesScale(), false, nullptr);
    if (!phy) {
        LOG("[FATAL] PxCreatePhysics");
        ctx->release(); fnd->release(); return 12;
    }

    PxDefaultCpuDispatcher* disp = PxDefaultCpuDispatcherCreate(2);
    PxSceneDesc sd(phy->getTolerancesScale());
    sd.gravity            = PxVec3(0.0f, 0.0f, 0.0f);
    sd.cpuDispatcher      = disp;
    sd.filterShader       = PxDefaultSimulationFilterShader;
    sd.cudaContextManager = ctx;
    sd.flags             |= PxSceneFlag::eENABLE_GPU_DYNAMICS;
    sd.broadPhaseType     = PxBroadPhaseType::eGPU;
    PxScene* sc = phy->createScene(sd);
    if (!sc) {
        LOG("[FATAL] createScene");
        disp->release(); phy->release(); ctx->release(); fnd->release(); return 13;
    }
    {
        const PxSceneFlags fl = sc->getFlags();
        const PxBroadPhaseType::Enum bp = sc->getBroadPhaseType();
        LOG("[SCENE_OK] gpu_dynamics=%d broadphase=%d (eGPU=4)",
            (fl & PxSceneFlag::eENABLE_GPU_DYNAMICS) ? 1 : 0, (int)bp);
    }

    PxPBDMaterial* mat = phy->createPBDMaterial(0.8f, 0.05f, 1e+6f, 0.001f, 0.5f, 0.005f, 0.05f, 0.0f, 0.0f);
    PxPBDParticleSystem* ps = phy->createPBDParticleSystem(*ctx);
    ps->setRestOffset(0.005f);
    ps->setContactOffset(0.007f);
    ps->setParticleContactOffset(0.007f);
    ps->setSolidRestOffset(0.005f);
    ps->setFluidRestOffset(0.0f);
    sc->addActor(*ps);
    const PxU32 phase = ps->createPhase(mat, PxParticlePhaseFlags(0));
    LOG("[PS_OK] phase=%u ctxValid=%d", phase, ctx->contextIsValid() ? 1 : 0);

    // --- Synthetic per-particle data (positions/velocities/phases) ---
    std::vector<PxVec4> positions(particle_count);
    std::vector<PxVec4> velocities(particle_count, PxVec4(0.0f));
    std::vector<PxU32>  phases(particle_count, phase);
    for (unsigned i = 0; i < anchor_count; ++i) {
        const float x = static_cast<float>(i % 64u) * 0.05f;
        const float y = static_cast<float>(i / 64u) * 0.05f;
        const float z = 1.0f;
        positions[i]                = PxVec4(x, y, z,         0.0f);  // anchor invMass=0
        positions[anchor_count + i] = PxVec4(x, y, z + 0.01f, 1.0f);  // child  invMass=1
    }

    // --- Springs (4000 pairs anchor[i] <-> child[anchor_count + i]) ---
    std::vector<PxParticleSpring> springs(anchor_count);
    for (unsigned i = 0; i < anchor_count; ++i) {
        springs[i].ind0      = i;
        springs[i].ind1      = anchor_count + i;
        springs[i].length    = 0.01f;
        springs[i].stiffness = 1.0e4f;
        springs[i].damping   = 0.001f;
        springs[i].pad       = 0.0f;
    }

    // --- Helper (allocates pinned host arrays — different code path
    //     from device cuMemAlloc, so a crash here would be a separate
    //     class of failure). ---
    LOG("[BEFORE_HELPER]");
    ExtGpu::PxParticleClothBufferHelper* helper = ExtGpu::PxCreateParticleClothBufferHelper(
        /*maxCloths=*/1u,
        /*maxTriangles=*/max_triangles,
        /*maxSprings=*/anchor_count,
        /*maxParticles=*/particle_count,
        ctx);
    if (!helper) { LOG("[FATAL] PxCreateParticleClothBufferHelper returned null"); return 20; }
    LOG("[HELPER_OK] ctxValid=%d", ctx->contextIsValid() ? 1 : 0);

    // --- Arm A vs Arm B branch point ---
    if (armA) {
        helper->addCloth(
            /*blendScale=*/0.0f, /*restVolume=*/0.0f, /*pressure=*/0.0f,
            /*triangles=*/nullptr, /*numTriangles=*/0u,
            /*springs=*/springs.data(), /*numSprings=*/anchor_count,
            /*restPositions=*/positions.data(), /*numParticles=*/particle_count);
        LOG("[ARM_A_ADDCLOTH_CALLED]");
    } else {
        LOG("[ARM_B_ADDCLOTH_SKIPPED]");
    }
    LOG("[HELPER_STATE] ctxValid=%d numCloths=%u numSprings=%u numTriangles=%u numParticles=%u",
        ctx->contextIsValid() ? 1 : 0,
        helper->getNumCloths(), helper->getNumSprings(),
        helper->getNumTriangles(), helper->getNumParticles());

    PxParticleClothDesc& clothDesc = helper->getParticleClothDesc();
    LOG("[CLOTH_DESC] nbCloths=%u nbTriangles=%u nbSprings=%u nbParticles=%u",
        clothDesc.nbCloths, clothDesc.nbTriangles, clothDesc.nbSprings, clothDesc.nbParticles);

    PxPartitionedParticleCloth output;
    if (armA) {
        PxParticleClothPreProcessor* pre = PxCreateParticleClothPreProcessor(ctx);
        if (!pre) { LOG("[FATAL] PxCreateParticleClothPreProcessor returned null"); return 21; }
        pre->partitionSprings(clothDesc, output);
        pre->release();
        LOG("[ARM_A_PARTITIONSPRINGS_CALLED]");
    } else {
        LOG("[ARM_B_PARTITIONSPRINGS_SKIPPED] output is default-constructed");
    }
    LOG("[PARTITION_OUTPUT] nbCloths=%u nbPartitions=%u nbSprings=%u remapOutputSize=%u",
        output.nbCloths, output.nbPartitions, output.nbSprings, output.remapOutputSize);
    LOG("[STAGE_1_DONE] ctxValid=%d", ctx->contextIsValid() ? 1 : 0);

    if (stage <= 1) {
        helper->release();
        sc->removeActor(*ps); ps->release(); mat->release();
        sc->release(); disp->release(); phy->release(); ctx->release(); fnd->release();
        return 0;
    }

    // --- Stage 2: cloth buffer creation (this is where the crash happens
    //     in the Blender variant of this code). ---
    ExtGpu::PxParticleBufferDesc bufDesc;
    bufDesc.maxParticles       = particle_count;
    bufDesc.numActiveParticles = particle_count;
    bufDesc.positions          = positions.data();
    bufDesc.velocities         = velocities.data();
    bufDesc.phases             = phases.data();

    LOG("[BEFORE_CREATE_CLOTH_BUFFER] bufDesc.numActive=%u maxParticles=%u",
        bufDesc.numActiveParticles, bufDesc.maxParticles);
    LOG("[BEFORE_CREATE_CLOTH_BUFFER] clothDesc.nbCloths=%u nbTriangles=%u nbSprings=%u nbParticles=%u",
        clothDesc.nbCloths, clothDesc.nbTriangles, clothDesc.nbSprings, clothDesc.nbParticles);
    LOG("[BEFORE_CREATE_CLOTH_BUFFER] output.nbCloths=%u nbPartitions=%u nbSprings=%u remapOutputSize=%u",
        output.nbCloths, output.nbPartitions, output.nbSprings, output.remapOutputSize);

    PxParticleClothBuffer* cb = ExtGpu::PxCreateAndPopulateParticleClothBuffer(
        bufDesc, clothDesc, output, ctx);
    LOG("[AFTER_CREATE_CLOTH_BUFFER] result_ptr=%p ctxValid=%d",
        (void*)cb, ctx->contextIsValid() ? 1 : 0);
    if (!cb || !ctx->contextIsValid()) {
        LOG("[FAIL_STAGE_2] cloth buffer creation failed or context invalidated");
        if (cb) cb->release();
        helper->release();
        sc->removeActor(*ps); ps->release(); mat->release();
        sc->release(); disp->release(); phy->release(); ctx->release(); fnd->release();
        return 22;
    }

    ps->addParticleBuffer(cb);
    LOG("[AFTER_ADD_BUFFER] ctxValid=%d", ctx->contextIsValid() ? 1 : 0);
    helper->release();
    LOG("[STAGE_2_DONE]");

    if (stage <= 2) {
        ps->removeParticleBuffer(cb); cb->release();
        sc->removeActor(*ps); ps->release(); mat->release();
        sc->release(); disp->release(); phy->release(); ctx->release(); fnd->release();
        return 0;
    }

    // --- Stage 3: simulate ---
    LOG("[BEFORE_SIMULATE]");
    sc->simulate(1.0f / 60.0f);
    LOG("[AFTER_SIMULATE] ctxValid=%d", ctx->contextIsValid() ? 1 : 0);
    sc->fetchResults(true);
    LOG("[AFTER_FETCH] ctxValid=%d", ctx->contextIsValid() ? 1 : 0);

    // Readback first + last particle
    PxVec4* dpos = cb->getPositionInvMasses();
    std::vector<PxVec4> rb(particle_count);
    ctx->acquireContext();
    ctx->getCudaContext()->memcpyDtoH(rb.data(), CUdeviceptr(dpos), sizeof(PxVec4) * particle_count);
    ctx->releaseContext();
    LOG("[READBACK] anchor[0]=(%f,%f,%f,w=%f) child[0]=(%f,%f,%f,w=%f)",
        rb[0].x, rb[0].y, rb[0].z, rb[0].w,
        rb[anchor_count].x, rb[anchor_count].y, rb[anchor_count].z, rb[anchor_count].w);
    LOG("[STAGE_3_DONE]");

    ps->removeParticleBuffer(cb); cb->release();
    sc->removeActor(*ps); ps->release(); mat->release();
    sc->release(); disp->release(); phy->release(); ctx->release(); fnd->release();
    return 0;
}
