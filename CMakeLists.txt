cmake_minimum_required(VERSION 3.25)
project(MGSPortableOpsRecomp VERSION 0.1.0 LANGUAGES C CXX)

set(MGSPO_GEN_DIR "${CMAKE_SOURCE_DIR}/build/mgspo/gen" CACHE PATH
    "Directory written by tools/mgspo/gen.py")
set(PSP_RECOMP_DIR "${CMAKE_SOURCE_DIR}/external/psp-recomp" CACHE PATH
    "Pinned psp-recomp checkout")
option(MGSPO_ENABLE_INSTRUCTION_TRACE "Keep instruction trace hooks" OFF)
option(MGSPO_ENABLE_D3D12 "Build the experimental SDL3/D3D12 renderer" OFF)
option(MGSPO_FETCH_SDL3
       "Download the pinned SDL3 package for the experimental renderer" ON)

if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/recomp.h")
  message(FATAL_ERROR
    "PSP_RECOMP_DIR is not a psp-recomp checkout. Initialize submodules.")
endif()
if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "Generated GNU C requires clang-cl, not MSVC cl")
endif()

if(MGSPO_ENABLE_D3D12)
  if(NOT WIN32)
    message(FATAL_ERROR "The experimental D3D12 renderer requires Windows.")
  endif()
  find_package(SDL3 CONFIG QUIET COMPONENTS SDL3-shared)
  if(NOT SDL3_FOUND)
    if(NOT MGSPO_FETCH_SDL3)
      message(FATAL_ERROR
        "SDL3 was not found. Set SDL3_DIR or enable MGSPO_FETCH_SDL3.")
    endif()
    include(FetchContent)
    FetchContent_Declare(mgspo_sdl3
      URL
        "https://github.com/libsdl-org/SDL/releases/download/release-3.2.20/SDL3-devel-3.2.20-VC.zip"
      URL_HASH
        "SHA256=33968846724F8B68D58AD0B42274E00E845FB4B35C0AC88CEDBE023A755116D4"
      DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
    FetchContent_GetProperties(mgspo_sdl3)
    if(NOT mgspo_sdl3_POPULATED)
      if(POLICY CMP0169)
        cmake_policy(PUSH)
        cmake_policy(SET CMP0169 OLD)
      endif()
      FetchContent_Populate(mgspo_sdl3)
      if(POLICY CMP0169)
        cmake_policy(POP)
      endif()
    endif()
    find_path(MGSPO_SDL3_CONFIG_DIR SDL3Config.cmake
      PATHS
        "${mgspo_sdl3_SOURCE_DIR}/cmake"
        "${mgspo_sdl3_SOURCE_DIR}/SDL3-3.2.20/cmake"
      NO_DEFAULT_PATH)
    if(NOT MGSPO_SDL3_CONFIG_DIR)
      message(FATAL_ERROR
        "The pinned SDL3 package did not contain SDL3Config.cmake.")
    endif()
    set(SDL3_DIR "${MGSPO_SDL3_CONFIG_DIR}" CACHE PATH
        "Directory containing SDL3Config.cmake" FORCE)
    find_package(SDL3 CONFIG REQUIRED COMPONENTS SDL3-shared)
  endif()
endif()

find_package(Python3 3.11 REQUIRED COMPONENTS Interpreter)
set(MGSPO_TOOLKIT_CHECK
    "${Python3_EXECUTABLE}"
    "${CMAKE_SOURCE_DIR}/tools/mgspo/toolkit_identity.py"
    --toolkit "${PSP_RECOMP_DIR}"
    --config "${CMAKE_SOURCE_DIR}/config/mgspo.toml"
    --manifest "${MGSPO_GEN_DIR}/mgspo_toolkit_identity.json")
execute_process(
  COMMAND ${MGSPO_TOOLKIT_CHECK}
  RESULT_VARIABLE MGSPO_TOOLKIT_RESULT)
if(NOT MGSPO_TOOLKIT_RESULT STREQUAL "0")
  message(FATAL_ERROR "psp-recomp identity verification failed.")
endif()

set(MGSPO_GEN_MANIFEST
    "${MGSPO_GEN_DIR}/mgspo_generated_sources.txt")
include("${CMAKE_SOURCE_DIR}/cmake/GeneratedSources.cmake")
mgspo_read_generated_sources("${MGSPO_GEN_DIR}" MGSPO_GEN_SRCS)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             "${MGSPO_GEN_MANIFEST}")

if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  get_filename_component(MGSPO_CLANG_BIN_DIR "${CMAKE_C_COMPILER}" DIRECTORY)
  set(MGSPO_LLVM_LIB "${MGSPO_CLANG_BIN_DIR}/llvm-lib.exe")
  if(NOT EXISTS "${MGSPO_LLVM_LIB}")
    message(FATAL_ERROR "llvm-lib.exe was not found beside clang-cl")
  endif()
  set(CMAKE_AR "${MGSPO_LLVM_LIB}")
  set(MGSPO_FP_FLAGS
      /fp:precise /clang:-ffp-contract=off /clang:-fno-strict-aliasing)
else()
  set(MGSPO_FP_FLAGS -ffp-contract=off -fno-strict-aliasing)
endif()

add_custom_target(mgspo_verify_toolkit
  COMMAND ${MGSPO_TOOLKIT_CHECK}
  COMMENT "Verifying the pinned psp-recomp checkout"
  VERBATIM)

set(MGSPO_BOOT_CONTRACT_DIR
    "${CMAKE_CURRENT_BINARY_DIR}/boot-contract")
set(MGSPO_BOOT_CONTRACT_HEADER
    "${MGSPO_BOOT_CONTRACT_DIR}/mgspo_boot_contract.h")
add_custom_command(
  OUTPUT "${MGSPO_BOOT_CONTRACT_HEADER}"
  COMMAND
    "${Python3_EXECUTABLE}"
    "${CMAKE_SOURCE_DIR}/tools/mgspo/boot_contract.py"
    --config "${CMAKE_SOURCE_DIR}/config/mgspo.toml"
    --output "${MGSPO_BOOT_CONTRACT_HEADER}"
  COMMAND "${CMAKE_COMMAND}" -E touch "${MGSPO_BOOT_CONTRACT_HEADER}"
  DEPENDS
    "${CMAKE_SOURCE_DIR}/config/mgspo.toml"
    "${CMAKE_SOURCE_DIR}/tools/mgspo/boot_contract.py"
    "${CMAKE_SOURCE_DIR}/tools/mgspo/oracle.py"
  COMMENT "Generating the verified MGSPO boot contract"
  VERBATIM)
add_custom_target(mgspo_boot_contract
  DEPENDS "${MGSPO_BOOT_CONTRACT_HEADER}")

add_library(mgspo_game STATIC ${MGSPO_GEN_SRCS})
add_dependencies(mgspo_game mgspo_verify_toolkit)
target_include_directories(mgspo_game PRIVATE
  "${PSP_RECOMP_DIR}/src/rt"
  "${MGSPO_GEN_DIR}")
target_compile_definitions(mgspo_game PRIVATE
  "SR_ENABLE_INSTRUCTION_TRACE=$<BOOL:${MGSPO_ENABLE_INSTRUCTION_TRACE}>")
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  target_compile_options(mgspo_game PRIVATE
    /W3 ${MGSPO_FP_FLAGS} "$<$<CONFIG:Release>:/O2>")
else()
  target_compile_options(mgspo_game PRIVATE
    -Wall -Wno-unused-label ${MGSPO_FP_FLAGS}
    "$<$<CONFIG:Release>:-O2>")
endif()

add_library(mgspo_module_policy OBJECT tools/mgspo/module_policy.c)
add_dependencies(mgspo_module_policy mgspo_boot_contract)
target_include_directories(mgspo_module_policy PRIVATE
  "${PSP_RECOMP_DIR}/src/rt"
  "${MGSPO_BOOT_CONTRACT_DIR}")
target_compile_definitions(mgspo_module_policy PRIVATE
  _CRT_SECURE_NO_WARNINGS)
target_compile_options(mgspo_module_policy PRIVATE ${MGSPO_FP_FLAGS})

add_custom_target(mgspo_bootstrap
  DEPENDS mgspo_game mgspo_module_policy)

set(MGSPO_RUNTIME_DIR "${PSP_RECOMP_DIR}/src/rt")
set(MGSPO_RUNTIME_SOURCES
  "${CMAKE_SOURCE_DIR}/src/mgspo_log.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_recomp.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_dispatch_table.c"
  "${MGSPO_RUNTIME_DIR}/fpu_mode.c"
  "${MGSPO_RUNTIME_DIR}/fps_counter.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_interp.cpp"
  "${PSP_RECOMP_DIR}/src/ref/interp.cpp"
  "${CMAKE_SOURCE_DIR}/src/mgspo_module.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_vfpu_interp.c"
  "${MGSPO_RUNTIME_DIR}/vfpu_asin.c"
  "${MGSPO_RUNTIME_DIR}/perf_stats.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_hle.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_kjfs_probe.c"
  "${MGSPO_RUNTIME_DIR}/display_state.c"
  "${MGSPO_RUNTIME_DIR}/memstick_state.c"
  "${MGSPO_RUNTIME_DIR}/net.c"
  "${MGSPO_RUNTIME_DIR}/kmem.c"
  "${MGSPO_RUNTIME_DIR}/intr.c"
  "${MGSPO_RUNTIME_DIR}/gelist.c"
  "${MGSPO_RUNTIME_DIR}/ge.c"
  "${MGSPO_RUNTIME_DIR}/callback.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_sched.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_iso.c"
  "${MGSPO_RUNTIME_DIR}/mpeg.c"
  "${MGSPO_RUNTIME_DIR}/pgf.c"
  "${MGSPO_RUNTIME_DIR}/gui.c"
  "${MGSPO_RUNTIME_DIR}/settings_path.c"
  "${MGSPO_RUNTIME_DIR}/graphics_config.c"
  "${MGSPO_RUNTIME_DIR}/graphics_settings.c"
  "${MGSPO_RUNTIME_DIR}/input_config.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_input_settings.c"
  "${CMAKE_SOURCE_DIR}/src/mgspo_runtime_settings.c"
  "${MGSPO_RUNTIME_DIR}/kzl_twinstick.c"
  "${MGSPO_RUNTIME_DIR}/startup_check.c"
  "${MGSPO_RUNTIME_DIR}/audio_mixer.c"
  "${MGSPO_RUNTIME_DIR}/sas_reverb.c"
  "${MGSPO_RUNTIME_DIR}/h264_mf.c"
  "${MGSPO_RUNTIME_DIR}/savedata.c"
  "${MGSPO_RUNTIME_DIR}/savedata_crypto.cpp"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/AES.c"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/SHA1.c"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/bn.c"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/ec.c"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/kirk_engine.c"
  "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata/chnnlsv.cpp"
  "${CMAKE_SOURCE_DIR}/src/mgspo_osk_win.c"
  "${MGSPO_RUNTIME_DIR}/audio_xaudio2.cpp"
  "${MGSPO_RUNTIME_DIR}/atrac_decode.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/atrac.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/atrac3.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/atrac3plus.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/atrac3plusdec.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/atrac3plusdsp.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/get_bits.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/compat.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/fft.cpp"
  "${PSP_RECOMP_DIR}/third_party/at3_standalone/mem.cpp")

if(MGSPO_ENABLE_D3D12)
  list(APPEND MGSPO_RUNTIME_SOURCES
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/device.cpp"
    "${CMAKE_SOURCE_DIR}/src/mgspo_d3d12_framebuffer.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/framebuffer_key.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/pipeline.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/pipeline_key.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/present.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/present_layout.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/smaa.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/shader_state.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/texture.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/texture_key.cpp"
    "${MGSPO_RUNTIME_DIR}/gpu_d3d12/vertex.cpp"
    "${MGSPO_RUNTIME_DIR}/texture_scaler.cpp"
    "${PSP_RECOMP_DIR}/third_party/xbrz/xbrz.cpp")
endif()

add_library(mgspo_runtime STATIC ${MGSPO_RUNTIME_SOURCES})
add_dependencies(mgspo_runtime mgspo_boot_contract)
target_include_directories(mgspo_runtime
  PUBLIC "${MGSPO_RUNTIME_DIR}"
  PRIVATE
    "${PSP_RECOMP_DIR}/src"
    "${PSP_RECOMP_DIR}/third_party/at3_standalone"
    "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata"
    "${MGSPO_BOOT_CONTRACT_DIR}")
target_compile_features(mgspo_runtime PRIVATE c_std_11 cxx_std_17)
target_compile_definitions(mgspo_runtime PRIVATE
  _CRT_SECURE_NO_WARNINGS)
target_compile_options(mgspo_runtime PRIVATE ${MGSPO_FP_FLAGS})
if(MGSPO_ENABLE_D3D12)
  target_compile_definitions(mgspo_runtime PRIVATE SR_D3D12)
  target_link_libraries(mgspo_runtime PUBLIC SDL3::SDL3 d3d12 dxgi)
endif()
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  target_compile_options(mgspo_runtime PRIVATE
    "/FI${MGSPO_BOOT_CONTRACT_HEADER}")
  set_source_files_properties(
    "${MGSPO_RUNTIME_DIR}/ge.c"
    PROPERTIES COMPILE_OPTIONS /O2)
endif()

add_executable(mgspo
  src/mgspo_main.c
  $<TARGET_OBJECTS:mgspo_module_policy>)
add_dependencies(mgspo
  mgspo_boot_contract
  mgspo_game
  mgspo_module_policy)
target_include_directories(mgspo PRIVATE
  "${MGSPO_RUNTIME_DIR}"
  "${MGSPO_BOOT_CONTRACT_DIR}")
target_compile_features(mgspo PRIVATE c_std_11)
target_compile_options(mgspo PRIVATE ${MGSPO_FP_FLAGS})
if(MGSPO_ENABLE_INSTRUCTION_TRACE)
  target_compile_definitions(mgspo PRIVATE MGSPO_TRACE_ENABLED=1)
endif()
if(MGSPO_ENABLE_D3D12)
  target_compile_definitions(mgspo PRIVATE MGSPO_D3D12_EXPERIMENTAL=1)
endif()
target_link_libraries(mgspo PRIVATE
  mgspo_game
  mgspo_runtime
  bcrypt
  comdlg32
  dinput8
  dxguid
  gdi32
  mf
  mfplat
  mfreadwrite
  mfuuid
  ole32
  propsys
  shell32
  shlwapi
  user32
  winmm
  xaudio2)
set_target_properties(mgspo PROPERTIES
  OUTPUT_NAME "MGSPortableOps")
add_custom_command(TARGET mgspo POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${MGSPO_GEN_DIR}/mgspo_image.bin"
    "$<TARGET_FILE_DIR:mgspo>/mgspo_image.bin"
  COMMAND "${CMAKE_COMMAND}" -E copy_directory
    "${PSP_RECOMP_DIR}/font"
    "$<TARGET_FILE_DIR:mgspo>/font"
  COMMAND "${CMAKE_COMMAND}" -E copy_directory
    "${PSP_RECOMP_DIR}/assets/vfpu"
    "$<TARGET_FILE_DIR:mgspo>/assets/vfpu"
  COMMENT "Staging the MGSPO runtime image and assets"
  VERBATIM)
if(MGSPO_ENABLE_D3D12)
  add_executable(mgspo_d3d12_write_sync_test EXCLUDE_FROM_ALL
    tools/mgspo/tests/d3d12_write_sync_test.cpp)
  target_compile_features(mgspo_d3d12_write_sync_test PRIVATE cxx_std_17)
  add_custom_command(TARGET mgspo POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
      "$<TARGET_FILE:SDL3::SDL3-shared>"
      "$<TARGET_FILE_DIR:mgspo>"
    COMMENT "Staging SDL3 for the experimental D3D12 renderer"
    VERBATIM)
endif()

install(TARGETS mgspo
  RUNTIME DESTINATION .)
install(FILES
  "${MGSPO_GEN_DIR}/mgspo_image.bin"
  "${CMAKE_SOURCE_DIR}/README.md"
  "${CMAKE_SOURCE_DIR}/LICENSE"
  DESTINATION .)
install(DIRECTORY
  "${PSP_RECOMP_DIR}/font/"
  DESTINATION font)
install(DIRECTORY
  "${PSP_RECOMP_DIR}/assets/vfpu/"
  DESTINATION assets/vfpu)
if(MGSPO_ENABLE_D3D12)
  install(IMPORTED_RUNTIME_ARTIFACTS SDL3::SDL3-shared
    RUNTIME DESTINATION .)
endif()
