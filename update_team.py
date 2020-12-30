from fpl import FPL
import aiohttp
import asyncio
from datetime import datetime, timedelta
import pandas as pd
async def update(email, password,user_id):
    async with aiohttp.ClientSession() as session:
        fpl = FPL(session)
        login = await fpl.login(email, password)
        user = await fpl.get_user(user_id)
        gw = await fpl.get_gameweeks(return_json=True)

        df = pd.DataFrame(gw)
        today = datetime.now().timestamp()
        df = df.loc[df.deadline_time_epoch>today]
        gameweek= df.iloc[0].id
        picks = await user.get_picks(gameweek-1)
        players = [x['element'] for x in picks[gameweek-1]]
        picked_players = []
        for player in players:
            p = await fpl.get_player(player, return_json=True)
            picked_players.append(p.copy())
        picked_players = pd.DataFrame(picked_players)
        picked_players.chance_of_playing_this_round= picked_players.chance_of_playing_this_round.fillna(100)

        fixtures = await fpl.get_fixtures_by_gameweek(gameweek, return_json=True)
        fixtures = pd.DataFrame(fixtures)

        picked_players = calc_fdr_diff(picked_players, fixtures)
        picked_players, player_out = calc_player_out(picked_players, fixtures)

        budget = user.last_deadline_bank+player_out.now_cost.iloc[0]
        dups_team = picked_players.pivot_table(index=['team'], aggfunc='size')
        invalid_teams = dups_team.loc[dups_team==3].index.tolist()
       
        potential_players = await fpl.get_players()

        player_dict = [dict(vars(x)) for x in potential_players]
        df=  pd.DataFrame(player_dict)

        df = df[~df['team'].isin(invalid_teams)]
        df = df[(df.now_cost<budget)]
        df= df.loc[~df['id'].isin(picked_players['id'].tolist())]
        df = df.loc[df.element_type==player_out.element_type.iloc[0]]

        rows_to_drop=player_out.index.values.astype(int)[0]
        picked_players=picked_players.drop(rows_to_drop)

        df = calc_fdr_diff(df, fixtures)
        player_in = calc_player_in(df, fixtures)

        transfer= await user.transfer(player_out.id.tolist(), player_in.id.tolist())
        player_in['id'] =player_out['id'].iloc[0]

        player_in, null_value=calc_player_out(player_in, fixtures) #dont need the player out
        picked_players=picked_players.append(player_in)
        players_to_sub_in, players_to_sub_out = calc_subs(picked_players, players[0:11], players[11:15])
        for i in range(0, len(players_to_sub_in)):
            s = await user.substitute([players_to_sub_in[i]],[players_to_sub_out[i]])

        captain=picked_players.sort_values(by=['weight']).iloc[0].id

def calc_subs(picked_players, current_starters, current_subs):

    goalkeepers=picked_players.loc[(picked_players.element_type=="") | (picked_players.element_type==1)]
    outfield = picked_players.loc[(picked_players.element_type!="G") & (picked_players.element_type!=1)]
    goalie = goalkeepers.sort_values(by=['weight']).iloc[0].id
    goalie_out = goalkeepers.sort_values(by=['weight']).iloc[1].id
    squad = outfield.sort_values(by=['weight']).iloc[0:10].id.tolist()
    squad.append(goalie)
    
    players_to_sub_in = []
    players_to_sub_out = []
    for player in picked_players.id.tolist():
        if player in squad and player in current_subs:
            players_to_sub_in.append(player)
        if player not in squad and player in current_starters:
            players_to_sub_out.append(player)
    return players_to_sub_in, players_to_sub_out

def calc_fdr_diff(players, fixes):
    fixes = fixes[['team_a', "team_h", "team_h_difficulty", "team_a_difficulty"]]
    away_df = pd.merge(players, fixes, how="inner", left_on=["team"], right_on=["team_a"])
    home_df = pd.merge(players, fixes, how="inner", left_on=["team"], right_on=["team_h"])
    if not away_df.empty:
        away_df['fdr'] = away_df['team_a_difficulty']-home_df['team_h_difficulty']-1
    if not home_df.empty:
        home_df['fdr'] = home_df['team_h_difficulty']-home_df['team_a_difficulty']+1
    df = away_df.append(home_df)
    df = df.drop(['team_a', "team_h", "team_h_difficulty", "team_a_difficulty"], axis=1)
    df.index = range(len(df))
    return df

def calc_player_out(players, fixtures):
    teams_playing = fixtures[["team_a", "team_h"]].values.ravel()
    teams_playing = pd.unique(teams_playing)
    ps_not_playing = players.loc[~players.team.isin(teams_playing)]
    teams_playing_twice = [x for x in teams_playing if list(teams_playing).count(x)>1]
    ps_playing_twice=players.loc[players.team.isin(teams_playing_twice)]
    df1 = pd.DataFrame(columns=players.columns.tolist())
    for x in players.iterrows():
        weight = 25
        weight-= x[1]['fdr']*3
        weight-= float(x[1]['form'])*4
        weight += (100-float(x[1]['chance_of_playing_this_round']))*0.2
        if x[1]['id'] in ps_not_playing['id']:
            weight+=25
        if x[1]['id'] in ps_playing_twice['id']:
            weight -=25
        if weight < 0:
            weight = 0.01
        x[1]['weight'] = weight
        df1 = df1.append(x[1])
    return df1, df1.sample(1, weights=df1.weight)

def calc_player_in(df, fixtures):
    df1 = pd.DataFrame(columns=df.columns.tolist())
    teams_playing = fixtures[["team_a", "team_h"]].values.ravel()
    teams_playing = pd.unique(teams_playing)
    teams_playing_twice = [x for x in teams_playing if list(teams_playing).count(x)>1]
    ps_not_playing = df.loc[~df.team.isin(teams_playing)]
    ps_playing_twice=df.loc[df.team.isin(teams_playing_twice)]
    for x in df.iterrows():
        weight = 0.1
        weight+= x[1]['fdr']*3
        weight+= float(x[1]['form'])*4
        weight -= (100-float(x[1]['chance_of_playing_this_round'])) * 0.2
        if weight < 0:
            weight = 0
        if x[1]['id'] in ps_not_playing['id']:
            weight+=5
        if x[1]['id'] in ps_playing_twice['id']:
            weight -=5
        if float(x[1]['form']) ==0:
            weight=0
        if weight < 0:
            weight = 0
        x[1]['weight'] = weight
        df1 = df1.append(x[1])
    df1=df1.sort_values('weight', ascending=False).iloc[0:10]
    return df1.sample(1, weights=df1.weight)