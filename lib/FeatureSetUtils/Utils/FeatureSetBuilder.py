import time
import os
import errno
import uuid
import csv
import math
import re

from Workspace.WorkspaceClient import Workspace as Workspace
from DataFileUtil.DataFileUtilClient import DataFileUtil
from KBaseReport.KBaseReportClient import KBaseReport


def log(message, prefix_newline=False):
    """Logging function, provides a hook to suppress or redirect log messages."""
    print(('\n' if prefix_newline else '') + '{0:.2f}'.format(time.time()) + ': ' + str(message))


class FeatureSetBuilder:

    def _mkdir_p(self, path):
        """
        _mkdir_p: make directory for given path
        """
        if not path:
            return
        try:
            os.makedirs(path)
        except OSError as exc:
            if exc.errno == errno.EEXIST and os.path.isdir(path):
                pass
            else:
                raise

    def _validate_upload_featureset_from_diff_expr_params(self, params):
        """
        _validate_upload_featureset_from_diff_expr_params:
                validates params passed to upload_featureset_from_diff_expr method
        """

        log('start validating upload_featureset_from_diff_expr params')

        # check for required parameters
        for p in ['diff_expression_ref', 'workspace_name',
                  'p_cutoff', 'q_cutoff', 'fold_scale_type', 'fold_change_cutoff']:
            if p not in params:
                raise ValueError('"{}" parameter is required, but missing'.format(p))

        fold_scale_type = params.get('fold_scale_type')
        validate_fold_scale_type = ['linear', 'logarithm']
        if fold_scale_type not in validate_fold_scale_type:
            error_msg = 'Input fold scale type value [{}] is not valid'.format(fold_scale_type)
            raise ValueError(error_msg)

    def _generate_report(self, up_feature_set_ref, down_feature_set_ref, 
                         filtered_expression_matrix_ref,
                         up_feature_ids, down_feature_ids, genome_id, workspace_name):
        """
        _generate_report: generate summary report
        """

        log('start creating report')

        output_html_files = self._generate_html_report(up_feature_ids, down_feature_ids, genome_id)
        objects_created = [{'ref': up_feature_set_ref,
                            'description': 'Upper FeatureSet Object'},
                           {'ref': down_feature_set_ref,
                            'description': 'Lower FeatureSet Object'}]

        if filtered_expression_matrix_ref:
            objects_created += [{'ref': filtered_expression_matrix_ref,
                                 'description': 'Filtered ExpressionMatrix Object'}]

        report_params = {'message': '',
                         'workspace_name': workspace_name,
                         'objects_created': objects_created,
                         'html_links': output_html_files,
                         'direct_html_link_index': 0,
                         'html_window_height': 333,
                         'report_object_name': 'kb_FeatureSetUtils_report_' + str(uuid.uuid4())}

        kbase_report_client = KBaseReport(self.callback_url)
        output = kbase_report_client.create_extended_report(report_params)

        report_output = {'report_name': output['name'], 'report_ref': output['ref']}

        return report_output

    def _generate_html_report(self, up_feature_ids, down_feature_ids, genome_id):
        """
        _generate_html_report: generate html summary report
        """

        log('start generating html report')
        html_report = list()

        output_directory = os.path.join(self.scratch, str(uuid.uuid4()))
        self._mkdir_p(output_directory)
        result_file_path = os.path.join(output_directory, 'report.html')

        genome_name = self.ws.get_object_info([{"ref": genome_id}],
                                              includeMetadata=None)[0][1]

        reference_genome_info = ''
        reference_genome_info += '{} ({})'.format(genome_name, genome_id)

        uppper_feature_ids_content = ''
        for feature_id in up_feature_ids:
            uppper_feature_ids_content += '<tr><td>{}</td><td>'.format(feature_id)

        lower_feature_ids_content = ''
        for feature_id in down_feature_ids:
            lower_feature_ids_content += '<tr><td>{}</td><td>'.format(feature_id)

        with open(result_file_path, 'w') as result_file:
            with open(os.path.join(os.path.dirname(__file__), 'report_template.html'),
                      'r') as report_template_file:
                report_template = report_template_file.read()
                report_template = report_template.replace('Reference_Genome_Info',
                                                          reference_genome_info)

                report_template = report_template.replace('Upper_Filtered_Features',
                                                          str(len(up_feature_ids)))

                report_template = report_template.replace('Lower_Filtered_Features',
                                                          str(len(down_feature_ids)))

                report_template = report_template.replace('<tr><td>Upper_Feature_IDs</td><td>',
                                                          uppper_feature_ids_content)

                report_template = report_template.replace('<tr><td>Lower_Feature_IDs</td><td>',
                                                          lower_feature_ids_content)

                result_file.write(report_template)

        html_report.append({'path': result_file_path,
                            'name': os.path.basename(result_file_path),
                            'label': os.path.basename(result_file_path),
                            'description': 'HTML summary report'})
        return html_report

    def _process_diff_expression(self, diff_expression_set_ref, result_directory):
        """
        _process_diff_expression: process differential expression object info
        """

        log('start processing differential expression object')

        diff_expr_set_data = self.ws.get_objects2({'objects':
                                                  [{'ref': 
                                                   diff_expression_set_ref}]})['data'][0]['data']

        set_items = diff_expr_set_data['items']

        diff_expr_matrix_file_name = 'gene_results.csv'
        diff_expr_matrix_file = os.path.join(result_directory, diff_expr_matrix_file_name)

        with open(diff_expr_matrix_file, 'w') as csvfile:
            fieldnames = ['gene_id', 'log2_fold_change', 'p_value', 'q_value']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

        for set_item in set_items:
            diff_expression_ref = set_item['ref']

            diff_expression_data = self.ws.get_objects2({'objects': 
                                                        [{'ref': 
                                                         diff_expression_ref}]})['data'][0]['data']

            genome_id = diff_expression_data['genome_ref']
            matrix_data = diff_expression_data['data']

            with open(diff_expr_matrix_file, 'ab') as csvfile:
                
                row_ids = matrix_data.get('row_ids')
                row_values = matrix_data.get('values')
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                for pos, row_id in enumerate(row_ids):
                    row_value = row_values[pos]
                    writer.writerow({'gene_id': row_id.split('.')[0],
                                     'log2_fold_change': row_value[0],
                                     'p_value': row_value[1],
                                     'q_value': row_value[2]})

        return diff_expr_matrix_file, genome_id

    def _generate_feature_set(self, feature_ids, genome_id, workspace_name, feature_set_name):
        """
        _generate_feature_set: generate FeatureSet object

        KBaseCollections.FeatureSet type:
        typedef structure {
            string description;
            list<feature_id> element_ordering;
            mapping<feature_id, list<genome_ref>> elements;
        } FeatureSet;
        """

        log('start saving KBaseCollections.FeatureSet object')

        if isinstance(workspace_name, int) or workspace_name.isdigit():
            workspace_id = workspace_name
        else:
            workspace_id = self.dfu.ws_name_to_id(workspace_name)

        elements = {}
        map(lambda feature_id: elements.update({feature_id: [genome_id]}), feature_ids)
        feature_set_data = {'description': 'Generated FeatureSet from DifferentialExpression',
                            'element_ordering': feature_ids,
                            'elements': elements}

        object_type = 'KBaseCollections.FeatureSet'
        save_object_params = {
            'id': workspace_id,
            'objects': [{'type': object_type,
                         'data': feature_set_data,
                         'name': feature_set_name}]}

        dfu_oi = self.dfu.save_objects(save_object_params)[0]
        feature_set_obj_ref = str(dfu_oi[6]) + '/' + str(dfu_oi[0]) + '/' + str(dfu_oi[4])

        return feature_set_obj_ref

    def _process_matrix_file(self, diff_expr_matrix_file, comp_p_value, comp_q_value,
                             fold_scale_type, comp_fold_change_cutoff):
        """
        _process_matrix_file: filter matrix file by given cutoffs
        """

        log('start processing matrix file')

        up_feature_ids = []
        down_feature_ids = []

        # if fold_scale_type == 'log2+1':
        #     comp_fold_change_cutoff = math.log(comp_fold_change_cutoff + 1, 2)
        # elif fold_scale_type == 'log10+1':
        #     comp_fold_change_cutoff = math.log10(comp_fold_change_cutoff + 1)

        with open(diff_expr_matrix_file, 'r') as file:
            reader = csv.DictReader(file)

            for row in reader:
                feature_id = row['gene_id']
                row_p_value = row['p_value']
                row_q_value = row['q_value']
                row_fold_change_cutoff = row['log2_fold_change']

                null_value = set(['NA', 'null', ''])
                col_value = set([row_p_value, row_q_value, row_fold_change_cutoff])

                if not col_value.intersection(null_value):
                    p_value_condition = float(row_p_value) <= comp_p_value
                    q_value_condition = float(row_q_value) <= comp_q_value

                    if fold_scale_type == 'linear':
                        row_fold_change_cutoff = float(row_fold_change_cutoff)
                        if row_fold_change_cutoff <= 0:
                            error_msg = 'Invalid Fold Change value '
                            error_msg += '[{}] for linear value. \n'.format(row_fold_change_cutoff)
                            error_msg += 'Available linear FC value should be greater than 0'
                            raise ValueError(error_msg)
                        row_fold_change_cutoff = math.log(row_fold_change_cutoff, 2)

                    up_matches_condition = (p_value_condition and q_value_condition and
                                            (float(row_fold_change_cutoff) >=
                                             comp_fold_change_cutoff))

                    down_matches_condition = (p_value_condition and q_value_condition and
                                              (float(row_fold_change_cutoff) <=
                                               -comp_fold_change_cutoff))

                if up_matches_condition:
                    up_feature_ids.append(feature_id)
                elif down_matches_condition:
                    down_feature_ids.append(feature_id)

        return list(set(up_feature_ids)), list(set(down_feature_ids))

    def _filter_expression_matrix(self, expression_matrix_ref, feature_ids, 
                                  workspace_name, filtered_expression_matrix_suffix):
        """
        _filter_expression_matrix: generated filtered expression matrix
        """

        log('start saving KBaseFeatureValues.ExpressionMatrix object')

        if isinstance(workspace_name, int) or workspace_name.isdigit():
            workspace_id = workspace_name
        else:
            workspace_id = self.dfu.ws_name_to_id(workspace_name)

        expression_matrix_obj = self.dfu.get_objects({'object_refs': 
                                                     [expression_matrix_ref]})['data'][0]

        expression_matrix_info = expression_matrix_obj['info']
        expression_matrix_data = expression_matrix_obj['data']

        expression_matrix_name = expression_matrix_info[1]

        if re.match('.*_*[Ee]xpression_*[Mm]atrix', expression_matrix_name):
            filtered_expression_matrix_name = re.sub('_*[Ee]xpression_*[Mm]atrix',
                                                     filtered_expression_matrix_suffix,
                                                     expression_matrix_name)
        else:
            filtered_expression_matrix_name = expression_matrix_name + filtered_expression_matrix_suffix

        filtered_expression_matrix_data = expression_matrix_data.copy()

        data = filtered_expression_matrix_data['data']

        row_ids = data['row_ids']
        values = data['values']
        filtered_data = data.copy()

        filtered_row_ids = list()
        filtered_values = list()
        for pos, row_id in enumerate(row_ids):
            if row_id.split('.')[0] in feature_ids:
                filtered_row_ids.append(row_id)
                filtered_values.append(values[pos])

        filtered_data['row_ids'] = filtered_row_ids
        filtered_data['values'] = filtered_values

        filtered_expression_matrix_data['data'] = filtered_data

        object_type = 'KBaseFeatureValues.ExpressionMatrix'
        save_object_params = {
            'id': workspace_id,
            'objects': [{'type': object_type,
                         'data': filtered_expression_matrix_data,
                         'name': filtered_expression_matrix_name}]}

        dfu_oi = self.dfu.save_objects(save_object_params)[0]
        filtered_expression_matrix_ref = str(dfu_oi[6]) + '/' + str(dfu_oi[0]) + '/' + str(dfu_oi[4])

        return filtered_expression_matrix_ref

    def __init__(self, config):
        self.ws_url = config["workspace-url"]
        self.callback_url = config['SDK_CALLBACK_URL']
        self.token = config['KB_AUTH_TOKEN']
        self.shock_url = config['shock-url']
        self.ws = Workspace(self.ws_url, token=self.token)
        self.dfu = DataFileUtil(self.callback_url)
        self.scratch = config['scratch']

    def upload_featureset_from_diff_expr(self, params):
        """
        upload_featureset_from_diff_expr: create FeatureSet from RNASeqDifferentialExpression
                                          based on given threshold cutoffs

        required params:
        diff_expression_ref: DifferetialExpressionMatrixSet object reference
        expression_matrix_ref: ExpressionMatrix object reference
        p_cutoff: p value cutoff
        q_cutoff: q value cutoff
        fold_scale_type: one of ["linear", "log2+1", "log10+1"]
        fold_change_cutoff: fold change cutoff
        feature_set_suffix: Result FeatureSet object name suffix
        filtered_expression_matrix_suffix: Result ExpressionMatrix object name suffix
        workspace_name: the name of the workspace it gets saved to

        return:
        result_directory: folder path that holds all files generated
        feature_set_ref: generated FeatureSet object reference
        filtered_expression_matrix_ref: generated filtered ExpressionMatrix object reference
        report_name: report name generated by KBaseReport
        report_ref: report reference generated by KBaseReport
        """

        self._validate_upload_featureset_from_diff_expr_params(params)

        diff_expression_set_ref = params.get('diff_expression_ref')
        diff_expression_set_info = self.ws.get_object_info3({"objects": 
                                                            [{"ref": diff_expression_set_ref}]}
                                                            )['infos'][0]
        diff_expression_set_name = diff_expression_set_info[1]

        result_directory = os.path.join(self.scratch, str(uuid.uuid4()))
        self._mkdir_p(result_directory)

        diff_expr_matrix_file, genome_id = self._process_diff_expression(
                                                            diff_expression_set_ref,
                                                            result_directory)

        up_feature_ids, down_feature_ids = self._process_matrix_file(
                                                                diff_expr_matrix_file,
                                                                params.get('p_cutoff'),
                                                                params.get('q_cutoff'),
                                                                params.get('fold_scale_type'),
                                                                params.get('fold_change_cutoff'))

        if params.get('expression_matrix_ref'):
            filtered_expression_matrix_ref = self._filter_expression_matrix(
                                                params.get('expression_matrix_ref'),
                                                up_feature_ids + down_feature_ids,
                                                params.get('workspace_name'),
                                                params.get('filtered_expression_matrix_suffix'))
        else:
            filtered_expression_matrix_ref = None

        up_feature_set_ref = self._generate_feature_set(
                            up_feature_ids,
                            genome_id,
                            params.get('workspace_name'),
                            diff_expression_set_name + '_up' + params.get('feature_set_suffix'))

        down_feature_set_ref = self._generate_feature_set(
                            down_feature_ids,
                            genome_id,
                            params.get('workspace_name'),
                            diff_expression_set_name + '_down' + params.get('feature_set_suffix'))

        returnVal = {'result_directory': result_directory,
                     'up_feature_set_ref': up_feature_set_ref,
                     'down_feature_set_ref': down_feature_set_ref,
                     'filtered_expression_matrix_ref': filtered_expression_matrix_ref}

        report_output = self._generate_report(up_feature_set_ref, down_feature_set_ref,
                                              filtered_expression_matrix_ref,
                                              up_feature_ids, down_feature_ids,
                                              genome_id,
                                              params.get('workspace_name'))
        returnVal.update(report_output)

        return returnVal
