#!/usr/bin/env bash
# Every release merged to main has a vX.Y.Z tag on its merge commit.
#
#   scripts/release-tags.sh                 list releases and whether each is tagged
#   scripts/release-tags.sh --check         exit 1 if a release has no tag or a wrong one
#   scripts/release-tags.sh --tag [--push]  create the missing tags (and push them, one at a time)
#
# A release is the first commit on main's first-parent history (the merge) where VERSION has a new
# value. Options: --ref REF (default origin/main, else HEAD), --grace HOURS (with --check: ignore
# releases merged less than HOURS ago, so the tag can follow the merge).
# Pushing tags one at a time lets GitHub start the release workflow for each; release.yml publishes
# images and a GitHub Release only for the newest version, so older tags just mark history.
set -euo pipefail
cd "$(dirname "$0")/.."

ref="" check=0 tag=0 push=0 grace=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) check=1 ;;
    --tag) tag=1 ;;
    --push) push=1 ;;
    --ref) ref="${2:?--ref needs a value}"; shift ;;
    --grace) grace="${2:?--grace needs hours}"; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "$grace" =~ ^[0-9]+$ ]] || { echo "--grace takes whole hours" >&2; exit 2; }
(( push == 0 || tag == 1 )) || { echo "--push needs --tag" >&2; exit 2; }
if [[ -z "$ref" ]]; then
  ref=origin/main
  git rev-parse -q --verify "$ref^{commit}" >/dev/null || ref=HEAD
fi

# Before pushing, see the tags origin already has (and where main is).
if (( push )); then git fetch -q origin main --tags; fi

now="$(date +%s)"
seen=" " missing=() wrong=0
# Oldest first; the first commit to carry each VERSION value is that release's merge.
while read -r commit when; do
  version="$(git show "$commit:VERSION" 2>/dev/null | tr -d '[:space:]')" || continue
  [[ -n "$version" && "$seen" != *" $version "* ]] || continue
  seen+="$version "
  name="v$version"
  short="$(git rev-parse --short "$commit")"
  if tagged="$(git rev-parse -q --verify "refs/tags/$name^{commit}")"; then
    if [[ "$tagged" == "$commit" ]]; then
      printf 'ok       %-9s %s\n' "$name" "$short"
    else
      printf 'WRONG    %-9s tag is on %s, release merge is %s\n' "$name" "$(git rev-parse --short "$tagged")" "$short"
      wrong=$((wrong + 1))
    fi
  elif (( now - when < grace * 3600 )); then
    printf 'pending  %-9s %s (merged under %sh ago)\n' "$name" "$short" "$grace"
  else
    printf 'MISSING  %-9s %s\n' "$name" "$short"
    missing+=("$name $commit")
  fi
done < <(git log --first-parent --reverse --format='%H %ct' "$ref" -- VERSION)

if (( tag )); then
  for item in "${missing[@]}"; do
    read -r name commit <<<"$item"
    git tag -a "$name" -m "Release ${name#v}" "$commit"
    echo "tagged   $name"
  done
  if (( push )); then
    for item in "${missing[@]}"; do
      read -r name _ <<<"$item"
      git push origin "refs/tags/$name"
    done
  elif (( ${#missing[@]} )); then
    echo "push them one at a time (newest last): scripts/release-tags.sh --tag --push, or git push origin <tag>"
  fi
  missing=()
fi

if (( wrong )); then
  echo "$wrong tag(s) point at the wrong commit; fix by hand (git tag -f, then git push -f origin <tag>)" >&2
fi
if (( ${#missing[@]} )); then
  echo "${#missing[@]} release(s) untagged: run scripts/release-tags.sh --tag --push" >&2
fi
if (( check && (${#missing[@]} || wrong) )); then exit 1; fi
