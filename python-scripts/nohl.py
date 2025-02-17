#               _    _ _                    
#              | |  | | |                   
#   _ __   ___ | |__| | |       _ __  _   _ 
#  | '_ \ / _ \|  __  | |      | '_ \| | | |
#  | | | | (_) | |  | | |____ _| |_) | |_| |
#  |_| |_|\___/|_|  |_|______(_) .__/ \__, |
#                              | |     __/ |
#                              |_|    |___/ 
# ===================================================================================================
# Author: Drazzilb
# Description: This script will find all files that are not hardlinked and will process them in Radarr
#              and Sonarr. This is useful for finding files that are not hardlinked and wish to have 100%
#              hardlinks seeding.
# Usage: python3 nohl.py
# Requirements: Python 3.8+, requests
# Version: 1.0.3
# License: MIT License
# ===================================================================================================


import os
import re
import sys
import time
import json
import re
from modules.config import Config
from modules.logger import setup_logger
from modules.arrpy import StARR
from unidecode import unidecode

config = Config(script_name="nohl")
logger = setup_logger(config.log_level, "nohl")

illegal_chars_regex = re.compile(r"[^\w\s\-\(\)/.'’]+")
season_regex = r"(?i)S(\d{2})E"
episode_regex = r"(?:E|e)(\d{1,2})"
title_regex = r".*\/([^/]+)\s\((\d{4})\).*"

def find_no_hl_files(media_paths):
    no_hl_files = []
    for dir in media_paths:
        try:
            logger.info(f"Processing directory: {dir}")
            for root, dirs, files in os.walk(dir):
                for file in files:
                    try:
                        if file.endswith(".mkv") or file.endswith(".mp4"):
                            file_path = os.path.join(root, file)
                            if (os.path.isfile(file_path) and os.stat(file_path).st_nlink == 1):
                                no_hl_files.append(file_path)
                    except Exception as e:
                        logger.warning(f"Error processing file: {file}. Error: {e}")
        except Exception as e:
            logger.warning(f"Error processing directory: {dir}. Error: {e}")
    return no_hl_files

def process_instances(instance_type, url, api, nohl_files, include_profiles, exclude_profiles, dry_run, exclude_series):
    nohl_files.sort()
    media_data = []
    media_data_episodes = []
    app = StARR(url, api, logger)
    media = app.get_media()
    title = None
    year = None
    season_number = None
    season_number_modified = None
    episode = None
    if instance_type == 'Radarr':
        for file in nohl_files:
            try:
                title_match = re.match(title_regex, file)
                if title_match:
                    title = title_match.group(1)
                    year = int(title_match.group(2))
            except Exception as e:
                logger.warning(f"Error processing file: {file}. Error: {e}")
            labled_data = {'title': title, 'year': year}
            media_data.append(labled_data)
    if instance_type == 'Sonarr':
        for file in nohl_files:
            try:
                season_number_match = re.search(season_regex, file)
                if season_number_match:
                    season_number = season_number_match.group(1)
            except Exception as e:
                logger.warning(f"Error processing file: {file}. Error: {e}")
            try:
                title = None
                match = re.match(title_regex, file)
                if match:
                    title = match.group(1)
                    year = int(match.group(2))
            except Exception as e:
                logger.warning(f"Error processing file: {file}. Error: {e}")
            try:
                episode_match = re.search(episode_regex, file)
                if episode_match:
                    episode = int(episode_match.group(1))
            except Exception as e:
                logger.warning(f"Error processing file: {file}. Error: {e}")
            if season_number:
                if season_number.startswith('0'):
                    season_number_modified = int(season_number[1:])
                else:
                    season_number_modified = int(season_number)
            existing_dict = next((d for d in media_data if d['title'] == title and d['year'] == year), None)
            if existing_dict:
                for season_info in existing_dict['season_info']:
                    if season_info['season_number'] == season_number_modified:
                        season_info['episodes'].append(episode)
                        break
                else:
                    existing_dict['season_info'].append({
                        'season_number': season_number_modified, 
                        'episodes': [episode]
                    })
            else:
                try:
                    media_data.append({
                        'title': title, 
                        'year': year, 
                        'season_info': [{
                            'season_number': season_number_modified, 
                            'episodes': [episode]
                        }]
                    })
                except Exception as e:
                    logger.warning(f"Error processing file: {file}. Error: {e}")
    logger.debug(f"Media Data: {json.dumps(media_data, indent=4)}")
    results = []
    file_ids = []
    quality_profiles = []
    quality_profiles = app.get_quality_profile_names()
    for media_data_item in media_data:
        media_data_item_title = media_data_item['title']
        media_data_item_title_modified = unidecode(media_data_item['title'])
        media_data_item_title_modified = illegal_chars_regex.sub("", media_data_item_title_modified)
        media_data_item_year = media_data_item['year']
        for media_item in media:
            quality_profile_id = None
            quality_profile_name = None
            media_item_title = media_item['title']
            media_item_title_modified = unidecode(re.sub(r' \(\d+\)', '', (media_item['title'])))
            media_item_title_modified = illegal_chars_regex.sub("", media_item_title_modified)
            media_item_year = media_item['year']
            media_item_id = media_item['id']
            media_item_monitored = media_item['monitored']
            quality_profile_id = media_item['qualityProfileId']
            if media_data_item_title_modified == media_item_title_modified and abs(media_data_item_year - media_item_year) == 1:
                logger.warning(f"Found match for {media_item_title} and {media_data_item_title} but years do not match. Media Year: {media_item_year}, File Year: {media_data_item_year}")
            strings_match = lambda s1, s2: re.sub(r'\W+', ' ', s1) == re.sub(r'\W+', ' ', s2).replace(':', '-')
            if strings_match(media_data_item_title_modified, media_item_title_modified) and media_data_item_year == media_item_year:
                if media_item_title in exclude_series if exclude_series else False:
                    logger.info(f"Skipping {media_item_title} because it is in the exclude list.")
                    continue
                if quality_profiles:
                    quality_profile_name = next(key for key, value in quality_profiles.items() if value == quality_profile_id)

                if (quality_profile_name in include_profiles if include_profiles else True) and (quality_profile_name not in exclude_profiles if exclude_profiles else True):
                    if instance_type == 'Radarr':
                        if media_item_monitored:
                            try:
                                file_ids = media_item['movieFile']['id']
                                logger.debug(f"Found match: {media_item_title}, Media ID: {media_item_title}, File IDs: {file_ids}")
                                results.append({
                                    'title': media_item_title_modified, 
                                    'media_id': media_item_id, 
                                    'file_ids': file_ids
                                })
                            except:
                                continue
                        else:
                            logger.info(f"Skipping {media_item_title} because it is not monitored.")
                            continue

                    elif instance_type == 'Sonarr':
                        monitored_seasons = []
                        media_data_seasons = [season['season_number'] for season in media_data_item['season_info']]
                        media_seasons = media_item['seasons']
                        episode_info = []

                        if media_item_monitored:
                            for s in media_seasons:
                                season_monitored = s['monitored']
                                if season_monitored:
                                    monitored_seasons.append(s['seasonNumber'])
                                else: 
                                    logger.debug(f"Skipping {media_item_title} because season {s['seasonNumber']} is not monitored.")
                            common_seasons = list(set(monitored_seasons) & set(media_data_seasons))
                            season_info = []

                            for item in media_seasons:
                                if item['seasonNumber'] in common_seasons:
                                    stats = item['statistics']
                                    episodeCount = stats['episodeFileCount']
                                    totalEpisodeCount = stats['totalEpisodeCount']
                                    season_pack = episodeCount == totalEpisodeCount
                                    season_info.append({
                                        'season_number': item['seasonNumber'], 
                                        'season_pack': season_pack, 
                                        'episode_info': []
                                    })

                            season_data = app.get_season_data(media_item_id)

                            for item in season_info:
                                season_number = item['season_number']
                                season_pack = item['season_pack']
                                episode_info = item['episode_info']
                                episode_file_id = []
                                episode_ids = []
                                episode_numbers = []

                                for season_data_item in season_data or []:
                                    if not season_data_item['monitored']:
                                        continue
                                    if season_data_item['seasonNumber'] == season_number:
                                        media_data_episodes = [episode for season in media_data_item['season_info'] if season['season_number'] == season_number for episode in season['episodes']]
                                        if season_pack:
                                            if season_data_item['episodeFileId'] not in episode_file_id:
                                                episode_file_id.append(season_data_item['episodeFileId'])
                                        elif not season_pack and season_data_item['episodeNumber'] in media_data_episodes:
                                            episode_file_id.append(season_data_item['episodeFileId'])
                                            episode_ids.append(season_data_item['id'])
                                            episode_numbers.append(season_data_item['episodeNumber'])

                                episode_info.append({
                                    'episode_file_id': episode_file_id, 
                                    'episode_ids': episode_ids, 
                                    'episode_numbers': episode_numbers
                                })
                            results.append({
                                'title': media_item_title,
                                'media_id': media_item_id, 
                                'seasons': season_info
                            })
                        else:
                            logger.info(f"Skipping {media_item_title} because it is not monitored.")
                            continue
                else:
                    if quality_profile_name:
                        logger.info(f"Skipping {media_item_title} because it does not meet quality profile requirements. Quality Profile: {quality_profile_name}")
                    else:
                        logger.info(f"Skipping {media_item_title} because it does not have a quality profile.")
                    continue
                
    logger.debug(f"Results: {json.dumps(results, indent=4)}")
    final_step(app, results, instance_type, dry_run)

def final_step(app, results, instance_type, dry_run):
    searches = config.maximum_searches
    logger.debug(f"Searches: {searches}")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = os.path.join(script_dir, 'tmp')
    tmp_file_path = f'{tmp_dir}/search_count.txt'
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    if not os.path.exists(tmp_file_path):
        try:
            with open(tmp_file_path, 'w') as f:
                f.write('0\n0')
        except OSError as e:
            logger.error(f"Error creating search count file: {e}")
            sys.exit(1)
    try:
        with open(tmp_file_path, 'r') as f:
            search_count, last_search_time = map(int, f.read().split('\n'))
    except ValueError:
        search_count, last_search_time = 0, 0
    current_time = int(time.time())
    if current_time - last_search_time >= 3600:
        search_count = 0
        last_search_time = current_time
    for result in results:
        if search_count >= searches:
            logger.warning('Maximum number of searches reached, cannot perform search')
            break
        media_id = result['media_id']
        title = result['title']
        if instance_type == 'Sonarr':
            seasons = result['seasons']
            for season in seasons:
                season_number = season['season_number']
                season_pack = season['season_pack']
                episode_info = season['episode_info']
                if season_pack:
                    episode_file_id = episode_info[0]['episode_file_id']
                    logger.debug(f"Processing {instance_type} - Deleting episode file for {title} Season {season_number}, Season Pack: {season_pack}")
                    if not dry_run:
                        app.delete_episode_files(episode_file_id)
                        app.refresh_media(media_id)
                        app.search_season(media_id, season_number)
                        logger.info(f"Deleted Season {season_number} for {title}, and a search request was sent to Sonarr for Season {season_number}")
                        search_count += 1
                    else:
                        logger.info(f"Would have deleted Season {season_number} for {title}, and the a search request would have been sent to Sonarr for Season {season_number}")
                elif not season_pack:
                    episode_file_id = episode_info[0]['episode_file_id']
                    episode_ids = episode_info[0]['episode_ids']
                    episode_numbers = episode_info[0]['episode_numbers']
                    logger.debug(f"Processing {instance_type} - Deleting episode file for {title} Season {season_number}, Season Pack: {season_pack}")
                    if not dry_run:
                        app.delete_episode_files(episode_file_id)
                        app.refresh_media(media_id)
                        app.search_episodes(episode_ids)
                        search_count += 1  
                        logger.info(f"Deleted episode file for {title} Season {season_number} episodes {episode_numbers}, search request sent to Sonarr")
                    else:
                        logger.info(f"Would have deleted episode files for {title} Season {season_number} episodes {episode_numbers}, and the individual episodes would have been searched for a replacement")
                logger.debug(f"Search counter: {search_count}")
        elif instance_type == 'Radarr':
            file_ids = result['file_ids']
            logger.debug(f"Processing {instance_type} - Deleting movie file for {title}")
            if not dry_run:
                app.delete_movie_file(file_ids)
                app.refresh_media(media_id)
                app.search_media(media_id)
                logger.info(f"Deleted movie file for {title}, and the movie was searched for a replacement")
                search_count += 1
            else:
                logger.info(f"Would have deleted movie file for {title}, and the movie would have been searched for a replacement")   
    logger.debug(f"Search Total: {search_count}")
    try:
        with open(tmp_file_path, 'w') as f:
            f.write(f'{search_count}\n{last_search_time}')
    except Exception as e:
        logger.error(f"Error writing to file: {e}")

def main():
    exclude_series = None
    instances_to_run = []
    include_profiles = None
    exclude_profiles = None
    dry_run = config.dry_run
    if config.dry_run:
        logger.info('*' * 40)
        logger.info(f'* {"Dry_run Activated":^36} *')
        logger.info('*' * 40)
        logger.info(f'* {" NO CHANGES WILL BE MADE ":^36} *')
        logger.info('*' * 40)
        logger.info('')
    search = config.maximum_searches
    if search >= 20:
        logger.error(f"Maximum searches set to {search}. This can cause devastating issues with your trackers. I will not be held responsible for any issues that arise from this. Please set this to a lower number.")
        logger.error(f"Exiting...")
        sys.exit()
    elif search >= 10:
        logger.warning(f"Maximum searches set to {search}. This can cause issues with your trackers. Please be careful.")
    elif search > 0 and search < 10:
        pass
    elif search == 0:
        logger.info(f"Maximum searches set to {search}, nothing will be searched for.")
    else:
        logger.error(f"Maximum searches set to {search}. This is not a valid number. Please set this to a positive number.")
        logger.error(f"Exiting...")
        sys.exit()
    paths = [] 
    monitored_paths = []
    for config_item in [config.radarr, config.sonarr]:
        for item in config_item or []:
            if item['paths']:
                paths.extend([item['paths']] if isinstance(item['paths'], str) else item['paths'])
                monitored_paths.extend([item['paths']] if isinstance(item['paths'], str) else item['paths'])
            else:
                logger.warning(f"No paths set for {item['name']}")
                continue
    nohl_files = find_no_hl_files(paths)
    if nohl_files:
        instances_to_run = []
        try:
            if config.script_data['radarr']:
                for radarr_config in config.script_data['radarr']:
                    if radarr_config['paths']:
                        for radarr_path in ([radarr_config['paths']] if isinstance(radarr_config['paths'], str) else radarr_config['paths']):
                            if any(nohl_path.startswith(radarr_path) for nohl_path in nohl_files):
                                instance_found = False
                                for instance in instances_to_run:
                                    if instance['instance_name'] == radarr_config['name']:
                                        instance['files_to_process'].extend([nohl_file for nohl_file in nohl_files if nohl_file.startswith(radarr_path)])
                                        instance_found = True
                                        break
                                if not instance_found:
                                    instances_to_run.append({
                                        'instance_name': radarr_config['name'], 
                                        'files_to_process':[nohl_file for nohl_file in nohl_files if nohl_file.startswith(radarr_path)]
                                    })
        except KeyError:
            logger.warning("No Radarr instances found in script_data")
        try:
            if config.script_data['sonarr']:
                for sonarr_config in config.script_data['sonarr']:
                    if sonarr_config['paths']:
                        for sonarr_path in ([sonarr_config['paths']] if isinstance(sonarr_config['paths'], str) else sonarr_config['paths']):
                            if any(nohl_path.startswith(sonarr_path) for nohl_path in nohl_files):
                                instance_found = False
                                for instance in instances_to_run:
                                    if instance['instance_name'] == sonarr_config['name']:
                                        instance['files_to_process'].extend([nohl_file for nohl_file in nohl_files if nohl_file.startswith(sonarr_path)])
                                        instance_found = True
                                        break
                                if not instance_found:
                                    instances_to_run.append({
                                        'instance_name': sonarr_config['name'], 
                                        'files_to_process':[nohl_file for nohl_file in nohl_files if nohl_file.startswith(sonarr_path)]
                                    })
        except KeyError:
            logger.warning("No Sonarr instances found in script_data")
        logger.debug(f"Instances to run: {json.dumps(instances_to_run, indent=4)}")
            
    instance_data = {
        'Radarr': config.radarr_data,
        'Sonarr': config.sonarr_data
    }
    for instance_type, instances in instance_data.items():
        for instance in instances:
            instance_name = instance['name']
            instance_type = instance_type.capitalize()
            url = instance['url']
            api = instance['api']
            if instances_to_run:
                for _instance in instances_to_run:
                    if instance_name == _instance['instance_name']:
                        if instance_type == "Radarr":
                            logger.debug(f"Running {instance_type} instance {instance_name}")
                            data = next((data for data in config.radarr if data['name'] == instance_name), None)
                            if data:
                                try:
                                    include_profiles = data['include_profiles']
                                    logger.debug(f"Include profiles: {include_profiles}")
                                    exclude_profiles = data['exclude_profiles']
                                    nohl_files = _instance['files_to_process']
                                except KeyError:
                                    logger.error(f"Missing include_profiles, exclude_profiles, or both in {instance_name} config. Please check your config.")
                                    logger.error(f"Exiting...")
                                    sys.exit()
                                logger.debug(f"Processing {len(nohl_files)} files")
                        elif instance_type == "Sonarr":
                            logger.debug(f"Running {instance_type} instance {instance_name}")
                            data = next((data for data in config.sonarr if data['name'] == instance_name), None)
                            if data:
                                try:
                                    include_profiles = data['include_profiles']
                                    logger.debug(f"Include profiles: {include_profiles}")
                                    exclude_profiles = data['exclude_profiles']
                                    logger.debug(f"Exclude profiles: {exclude_profiles}")
                                    exclude_series = data['exclude_series']
                                    logger.debug(f"Exclude series: {exclude_series}")
                                except KeyError:
                                    logger.error(f"Missing include_profiles, exclude_profiles, or both in {instance_name} config. Please check your config.")
                                    logger.error(f"Exiting...")
                                    sys.exit()
                                nohl_files = _instance['files_to_process']
                                logger.debug(f"Processing {len(nohl_files)} files")
                        process_instances(instance_type, url, api, nohl_files, include_profiles, exclude_profiles, dry_run, exclude_series)

if __name__ == "__main__":
    main()