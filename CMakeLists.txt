cmake_minimum_required(VERSION 3.25)
project(MGSPortableOpsRecomp VERSION 0.1.0 LANGUAGES C CXX)

set(MGSPO_GEN_DIR "${CMAKE_SOURCE_DIR}/build/mgspo/gen" CACHE PATH
    "Directory written by tools/mgspo/gen.py")
set(PSP_RECOMP_DIR "${CMAKE_SOURCE_DIR}/external/psp-recomp" CACHE PATH
    "Pinned psp-recomp checkout")
option(MGSPO_ENABLE_INSTRUCTION_TRACE "Keep instruction trace hooks" OFF)

if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/recomp.h")
  message(FATAL_ERROR
    "PSP_RECOMP_DIR is not a psp-recomp checkout. Initialize submodules.")
endif()
if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "Generated GNU C requires clang-cl, not MSVC cl")
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
target_include_directories(mgspo_module_policy PRIVATE
  "${PSP_RECOMP_DIR}/src/rt")
target_compile_options(mgspo_module_policy PRIVATE ${MGSPO_FP_FLAGS})

add_custom_target(mgspo_bootstrap
  DEPENDS mgspo_game mgspo_module_policy)

message(STATUS
  "Standalone runtime target is intentionally disabled until the "
  "Portable Ops start-thread contract is measured.")
